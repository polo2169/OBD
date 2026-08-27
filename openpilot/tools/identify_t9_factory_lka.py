#!/usr/bin/env python3
"""Identify an apparent T9 factory-LKA response from passive recordings.

This is a closed-loop, read-only analysis.  It deliberately reports an
*apparent* relationship between the observed 0x3F2 command and lateral
acceleration; it cannot prove the open-loop EPS actuator gain or authorize TX.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

try:
    from tools.simulate_t9_torque import (
        DEFAULT_DBC,
        DEFAULT_OUTPUT_ROOT,
        ReplaySample,
        SimulatorConfig,
        load_session_samples,
    )
except ModuleNotFoundError:  # Direct execution from openpilot/tools.
    from simulate_t9_torque import (
        DEFAULT_DBC,
        DEFAULT_OUTPUT_ROOT,
        ReplaySample,
        SimulatorConfig,
        load_session_samples,
    )


@dataclass(frozen=True)
class IdentificationConfig:
    minimum_factor_raw: int = 90
    required_lka_state_raw: int = 4
    required_eps_state_raw: int = 3
    maximum_gap_s: float = 0.15
    maximum_adaptive_gap_s: float = 0.40
    minimum_burst_samples: int = 10
    minimum_burst_duration_s: float = 1.50
    maximum_lag_ms: int = 500
    lag_grid_ms: int = 50


def effective_factory_torque_raw(sample: ReplaySample) -> float:
    torque = float(sample.observed_lka_torque_raw or 0.0)
    factor = float(sample.observed_lka_torque_factor_raw or 0.0)
    return torque * factor / 100.0


def is_sustained_factory_lka(sample: ReplaySample, config: IdentificationConfig) -> bool:
    return (
        sample.observed_lka_state_raw == config.required_lka_state_raw
        and (sample.observed_lka_torque_factor_raw or 0) >= config.minimum_factor_raw
        and sample.eps_state_lka_raw == config.required_eps_state_raw
        and sample.can_age_s <= 0.25
        and sample.eps_status_age_s <= 0.25
    )


def split_active_bursts(
    samples: Sequence[ReplaySample],
    config: IdentificationConfig,
) -> list[list[ReplaySample]]:
    bursts: list[list[ReplaySample]] = []
    for sample in samples:
        if not is_sustained_factory_lka(sample, config):
            continue
        if (
            not bursts
            or bursts[-1][-1].session_id != sample.session_id
        ):
            bursts.append([sample])
        else:
            previous = bursts[-1][-1]
            adaptive_gap_s = max(
                config.maximum_gap_s,
                min(
                    config.maximum_adaptive_gap_s,
                    2.5 * max(previous.dt_s, sample.dt_s),
                ),
            )
            if sample.elapsed_s - previous.elapsed_s > adaptive_gap_s:
                bursts.append([sample])
            else:
                bursts[-1].append(sample)
    return [
        burst for burst in bursts
        if len(burst) >= config.minimum_burst_samples
        and burst[-1].elapsed_s - burst[0].elapsed_s >= config.minimum_burst_duration_s
    ]


def _ols(features: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    design = np.column_stack([np.ones(len(target)), features])
    coefficients, _, _, _ = np.linalg.lstsq(design, target, rcond=None)
    prediction = design @ coefficients
    residual = target - prediction
    denominator = float(np.sum((target - np.mean(target)) ** 2))
    return {
        "coefficients": coefficients,
        "prediction": prediction,
        "rmse": float(np.sqrt(np.mean(residual * residual))),
        "r_squared": 1.0 - float(np.sum(residual * residual)) / denominator if denominator else 0.0,
        "condition_number": float(np.linalg.cond(design)),
    }


def _correlation(first: np.ndarray, second: np.ndarray) -> float:
    if len(first) < 3 or float(np.std(first)) <= 1e-12 or float(np.std(second)) <= 1e-12:
        return 0.0
    return float(np.corrcoef(first, second)[0, 1])


def _static_rows(
    bursts: Sequence[Sequence[ReplaySample]],
    lag_steps: int,
    lag_grid_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features: list[tuple[float, float]] = []
    target: list[float] = []
    burst_ids: list[int] = []
    lag_s = lag_steps * lag_grid_s
    for burst_id, burst in enumerate(bursts):
        times = np.asarray([sample.elapsed_s for sample in burst])
        responses = np.asarray([
            sample.measured_lateral_accel_yaw_ms2 for sample in burst
        ])
        for command in burst:
            response_time = command.elapsed_s + lag_s
            if response_time > times[-1]:
                continue
            features.append((effective_factory_torque_raw(command), command.driver_torque_raw))
            target.append(float(np.interp(response_time, times, responses)))
            burst_ids.append(burst_id)
    return np.asarray(features), np.asarray(target), np.asarray(burst_ids)


def scan_static_alignment(
    bursts: Sequence[Sequence[ReplaySample]],
    maximum_lag_steps: int,
    sample_period_s: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for lag_steps in range(maximum_lag_steps + 1):
        features, target, _ = _static_rows(bursts, lag_steps, sample_period_s)
        if len(target) < 3:
            continue
        fit = _ols(features, target)
        results.append({
            "lag_steps": lag_steps,
            "lag_ms": 1000.0 * lag_steps * sample_period_s,
            "samples": len(target),
            "command_response_correlation": _correlation(features[:, 0], target),
            "apparent_gain_ms2_per_effective_raw": float(fit["coefficients"][1]),
            "driver_coefficient_ms2_per_raw": float(fit["coefficients"][2]),
            "intercept_ms2": float(fit["coefficients"][0]),
            "rmse_ms2": fit["rmse"],
            "r_squared": fit["r_squared"],
            "condition_number": fit["condition_number"],
        })
    return results


def _arx_rows(
    burst: Sequence[ReplaySample],
    delay_steps: int,
    lag_grid_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    features: list[tuple[float, float, float]] = []
    derivative_target: list[float] = []
    persistence: list[float] = []
    dt_values: list[float] = []
    response_target: list[float] = []
    times = np.asarray([sample.elapsed_s for sample in burst])
    commands = np.asarray([effective_factory_torque_raw(sample) for sample in burst])
    driver_torques = np.asarray([sample.driver_torque_raw for sample in burst])
    delay_s = delay_steps * lag_grid_s
    for index in range(len(burst) - 1):
        previous = burst[index]
        response = burst[index + 1]
        dt_s = response.elapsed_s - previous.elapsed_s
        command_time = previous.elapsed_s - delay_s
        if dt_s <= 0.01 or dt_s > 0.50 or command_time < times[0]:
            continue
        features.append((
            previous.measured_lateral_accel_yaw_ms2,
            float(np.interp(command_time, times, commands)),
            float(np.interp(command_time, times, driver_torques)),
        ))
        derivative_target.append(
            (
                response.measured_lateral_accel_yaw_ms2
                - previous.measured_lateral_accel_yaw_ms2
            ) / dt_s
        )
        persistence.append(previous.measured_lateral_accel_yaw_ms2)
        dt_values.append(dt_s)
        response_target.append(response.measured_lateral_accel_yaw_ms2)
    return (
        np.asarray(features),
        np.asarray(derivative_target),
        np.asarray(persistence),
        np.asarray(dt_values),
        np.asarray(response_target),
    )


def _leave_one_burst_out_arx(
    bursts: Sequence[Sequence[ReplaySample]],
    delay_steps: int,
    sample_period_s: float,
) -> dict[str, Any]:
    datasets = [_arx_rows(burst, delay_steps, sample_period_s) for burst in bursts]
    predictions: list[float] = []
    targets: list[float] = []
    persistence: list[float] = []
    fold_gains: list[float] = []
    fold_time_constants: list[float] = []
    fold_coefficients: list[list[float]] = []
    for held_out, (
        test_features,
        _,
        test_persistence,
        test_dt,
        test_response,
    ) in enumerate(datasets):
        train_features = np.concatenate([
            item[0] for index, item in enumerate(datasets) if index != held_out
        ])
        train_target = np.concatenate([
            item[1] for index, item in enumerate(datasets) if index != held_out
        ])
        fit = _ols(train_features, train_target)
        coefficients = np.asarray(fit["coefficients"])
        derivative_prediction = np.column_stack([
            np.ones(len(test_response)), test_features,
        ]) @ coefficients
        prediction = test_persistence + test_dt * derivative_prediction
        predictions.extend(float(value) for value in prediction)
        targets.extend(float(value) for value in test_response)
        persistence.extend(float(value) for value in test_persistence)
        a_coefficient = float(coefficients[1])
        input_coefficient = float(coefficients[2])
        if a_coefficient < -1e-3:
            fold_gains.append(-input_coefficient / a_coefficient)
            fold_time_constants.append(-1.0 / a_coefficient)
        fold_coefficients.append([float(value) for value in coefficients])

    target_array = np.asarray(targets)
    prediction_array = np.asarray(predictions)
    persistence_array = np.asarray(persistence)
    residual = target_array - prediction_array
    persistence_residual = target_array - persistence_array
    denominator = float(np.sum((target_array - np.mean(target_array)) ** 2))
    rmse = float(np.sqrt(np.mean(residual * residual)))
    persistence_rmse = float(np.sqrt(np.mean(persistence_residual * persistence_residual)))
    return {
        "delay_steps": delay_steps,
        "delay_ms": 1000.0 * delay_steps * sample_period_s,
        "samples": len(target_array),
        "cross_validated_rmse_ms2": rmse,
        "persistence_rmse_ms2": persistence_rmse,
        "improvement_over_persistence_fraction": (
            1.0 - rmse / persistence_rmse if persistence_rmse else 0.0
        ),
        "cross_validated_r_squared": (
            1.0 - float(np.sum(residual * residual)) / denominator if denominator else 0.0
        ),
        "leave_one_burst_out_dc_gains": fold_gains,
        "dc_gain_median_ms2_per_effective_raw": (
            float(statistics.median(fold_gains)) if fold_gains else None
        ),
        "dc_gain_min_ms2_per_effective_raw": min(fold_gains) if fold_gains else None,
        "dc_gain_max_ms2_per_effective_raw": max(fold_gains) if fold_gains else None,
        "time_constant_median_s": (
            float(statistics.median(fold_time_constants))
            if fold_time_constants else None
        ),
        "model_form": "d(a_lat)/dt = intercept + a*a_lat + b*u_lka + c*u_driver",
        "fold_coefficients": fold_coefficients,
    }


def scan_arx_delays(
    bursts: Sequence[Sequence[ReplaySample]],
    maximum_delay_steps: int,
    sample_period_s: float,
) -> list[dict[str, Any]]:
    return [
        _leave_one_burst_out_arx(bursts, delay_steps, sample_period_s)
        for delay_steps in range(maximum_delay_steps + 1)
    ]


def summarize_bursts(
    bursts: Sequence[Sequence[ReplaySample]],
    static_lag_steps: int,
    lag_grid_s: float,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for index, burst in enumerate(bursts, start=1):
        features, target, _ = _static_rows([burst], static_lag_steps, lag_grid_s)
        fit = _ols(features, target)
        commands = [effective_factory_torque_raw(sample) for sample in burst]
        summaries.append({
            "burst_id": f"burst-{index:02d}",
            "session_id": burst[0].session_id,
            "start_s": burst[0].elapsed_s,
            "end_s": burst[-1].elapsed_s,
            "duration_s": burst[-1].elapsed_s - burst[0].elapsed_s,
            "samples": len(burst),
            "speed_min_kph": min(sample.speed_kph for sample in burst),
            "speed_max_kph": max(sample.speed_kph for sample in burst),
            "effective_torque_min_raw": min(commands),
            "effective_torque_max_raw": max(commands),
            "apparent_gain_ms2_per_effective_raw": float(fit["coefficients"][1]),
            "driver_coefficient_ms2_per_raw": float(fit["coefficients"][2]),
            "r_squared": fit["r_squared"],
            "rmse_ms2": fit["rmse"],
        })
    return summaries


def build_identifiability_assessment(
    session_summaries: Sequence[dict[str, Any]],
    bursts: Sequence[dict[str, Any]],
    static_best: dict[str, Any],
    arx_best: dict[str, Any],
) -> dict[str, Any]:
    observed_active_sessions = sum(
        1 for item in session_summaries if item["active_samples"] > 0
    )
    usable_active_sessions = len({str(item["session_id"]) for item in bursts})
    burst_gains = [
        float(item["apparent_gain_ms2_per_effective_raw"])
        for item in bursts
    ]
    median_burst_gain = statistics.median(burst_gains) if burst_gains else math.nan
    gain_spread = max(burst_gains) - min(burst_gains) if burst_gains else math.inf
    relative_spread = gain_spread / abs(median_burst_gain) if median_burst_gain else math.inf
    informative_burst_gains = [
        float(item["apparent_gain_ms2_per_effective_raw"])
        for item in bursts if float(item.get("r_squared", 0.0)) >= 0.50
    ]
    if informative_burst_gains:
        first_quartile, third_quartile = np.percentile(
            informative_burst_gains, [25, 75]
        )
        informative_iqr_relative = (
            float(third_quartile - first_quartile)
            / abs(statistics.median(informative_burst_gains))
        )
    else:
        informative_iqr_relative = math.inf
    gains_by_session: dict[str, list[float]] = {}
    for item in bursts:
        gains_by_session.setdefault(str(item["session_id"]), []).append(
            float(item["apparent_gain_ms2_per_effective_raw"])
        )
    session_gain_medians = {
        session_id: statistics.median(values)
        for session_id, values in gains_by_session.items()
    }
    if session_gain_medians:
        session_values = list(session_gain_medians.values())
        session_gain_relative_spread = (
            (max(session_values) - min(session_values))
            / abs(statistics.median(session_values))
        )
    else:
        session_gain_relative_spread = math.inf
    static_gain = float(static_best["apparent_gain_ms2_per_effective_raw"])
    dynamic_gain = float(arx_best["dc_gain_median_ms2_per_effective_raw"])
    gains_agree = abs(static_gain - dynamic_gain) / max(abs(dynamic_gain), 1e-9) <= 0.15
    delay_agrees = abs(float(static_best["lag_ms"]) - float(arx_best["delay_ms"])) <= 100.0
    gates = {
        "at_least_1000_active_samples": sum(
            int(item["active_samples"]) for item in session_summaries
        ) >= 1000,
        "at_least_5_independent_bursts": len(bursts) >= 5,
        "active_lka_in_at_least_2_sessions": usable_active_sessions >= 2,
        "static_and_dynamic_gain_within_15_percent": gains_agree,
        "informative_burst_gain_iqr_below_30_percent": informative_iqr_relative <= 0.30,
        "session_median_gain_spread_below_15_percent": (
            session_gain_relative_spread <= 0.15
        ),
        "static_and_dynamic_delay_within_100_ms": delay_agrees,
        "arx_improves_persistence_by_5_percent": (
            float(arx_best["improvement_over_persistence_fraction"]) >= 0.05
        ),
    }
    return {
        "gates": gates,
        "passes_all_identifiability_gates": all(gates.values()),
        "observed_active_session_count": observed_active_sessions,
        "active_session_count": usable_active_sessions,
        "burst_gain_median_ms2_per_effective_raw": median_burst_gain,
        "burst_gain_relative_spread": relative_spread,
        "informative_burst_gain_iqr_relative": informative_iqr_relative,
        "session_gain_medians_ms2_per_effective_raw": session_gain_medians,
        "session_gain_relative_spread": session_gain_relative_spread,
        "closed_loop_identification_only": True,
        "open_loop_eps_gain_validated": False,
        "vehicle_calibration_ready": False,
        "hil_gain_prior_confidence": "medium",
        "physical_delay_confidence": "unvalidated",
        "vehicle_parameter_confidence": "low",
        "conclusion": (
            "La capture fournit un prior numérique pour le HIL, mais pas un gain "
            "actionneur EPS causal. La commande usine, le conducteur et la courbure "
            "évoluent ensemble en boucle fermée."
        ),
    }


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 6)
    if isinstance(value, np.floating):
        return _round(float(value))
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, dict):
        return {key: _round(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round(item) for item in value]
    return value


def _write_active_csv(path: Path, bursts: Sequence[Sequence[ReplaySample]]) -> None:
    fields = [
        "burst_id", "session_id", "elapsed_s", "speed_kph",
        "lka_torque_raw", "torque_factor_raw", "effective_torque_raw",
        "driver_torque_raw", "lateral_accel_yaw_ms2", "eps_state_lka_raw",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for burst_index, burst in enumerate(bursts, start=1):
            for sample in burst:
                writer.writerow({
                    "burst_id": f"burst-{burst_index:02d}",
                    "session_id": sample.session_id,
                    "elapsed_s": round(sample.elapsed_s, 4),
                    "speed_kph": round(sample.speed_kph, 3),
                    "lka_torque_raw": sample.observed_lka_torque_raw,
                    "torque_factor_raw": sample.observed_lka_torque_factor_raw,
                    "effective_torque_raw": round(effective_factory_torque_raw(sample), 4),
                    "driver_torque_raw": sample.driver_torque_raw,
                    "lateral_accel_yaw_ms2": round(
                        sample.measured_lateral_accel_yaw_ms2, 6
                    ),
                    "eps_state_lka_raw": sample.eps_state_lka_raw,
                })


def _write_bursts_csv(path: Path, bursts: Sequence[dict[str, Any]]) -> None:
    if not bursts:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(bursts[0]))
        writer.writeheader()
        writer.writerows(bursts)


def _write_html(path: Path, report: dict[str, Any]) -> None:
    def number(value: Any, digits: int) -> str:
        return "n/a" if value is None else f"{float(value):.{digits}f}"

    static_rows = "".join(
        "<tr>"
        f"<td>{item['lag_ms']:.0f}</td>"
        f"<td>{item['command_response_correlation']:.4f}</td>"
        f"<td>{item['apparent_gain_ms2_per_effective_raw']:.5f}</td>"
        f"<td>{item['r_squared']:.4f}</td>"
        "</tr>"
        for item in report["static_alignment_scan"]
    )
    arx_rows = "".join(
        "<tr>"
        f"<td>{item['delay_ms']:.0f}</td>"
        f"<td>{item['cross_validated_rmse_ms2']:.4f}</td>"
        f"<td>{100*item['improvement_over_persistence_fraction']:.1f}%</td>"
        f"<td>{number(item['dc_gain_median_ms2_per_effective_raw'], 5)}</td>"
        f"<td>{number(item['time_constant_median_s'], 3)}</td>"
        "</tr>"
        for item in report["dynamic_arx_delay_scan"]
    )
    burst_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['burst_id'])}</td>"
        f"<td>{item['start_s']:.1f}–{item['end_s']:.1f}</td>"
        f"<td>{item['duration_s']:.1f}</td>"
        f"<td>{item['speed_min_kph']:.1f}–{item['speed_max_kph']:.1f}</td>"
        f"<td>{item['effective_torque_min_raw']:.1f}…{item['effective_torque_max_raw']:.1f}</td>"
        f"<td>{item['apparent_gain_ms2_per_effective_raw']:.5f}</td>"
        f"<td>{item['r_squared']:.3f}</td>"
        "</tr>"
        for item in report["bursts"]
    )
    gate_rows = "".join(
        "<li>"
        f"{'✅' if passed else '❌'} {html.escape(name.replace('_', ' '))}"
        "</li>"
        for name, passed in report["identifiability"]["gates"].items()
    )
    prior = report["simulation_prior"]
    path.write_text(f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Identification LKA usine T9</title><style>
body{{font:15px system-ui,sans-serif;margin:0;background:#10151d;color:#e9eef5}}main{{max-width:1120px;margin:auto;padding:28px}}
.warning{{background:#4b2b09;border:1px solid #d78b28;padding:16px;border-radius:10px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}}
.card,table,section{{background:#18212c;border:1px solid #2b3949;border-radius:10px;padding:14px}}.value{{font-size:25px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;text-align:right;border-bottom:1px solid #2b3949}}th:first-child,td:first-child{{text-align:left}}code{{color:#8fd3ff}}
</style></head><body><main><h1>Identification passive du LKA usine — Peugeot 308 T9</h1>
<p class="warning"><strong>Ce rapport n'identifie pas causalement l'actionneur EPS.</strong> Il analyse une boucle fermée où commande usine, conducteur et route évoluent ensemble. Aucun port série, aucune émission CAN, aucune commande véhicule.</p>
<div class="cards"><div class="card"><div>Prior HIL central</div><div class="value">{prior['central_gain_ms2_per_effective_raw']:.4f}</div><small>m/s²/raw effectif</small></div>
<div class="card"><div>Plage leave-one-burst-out</div><div class="value">{prior['sensitivity_min']:.4f}–{prior['sensitivity_max']:.4f}</div></div>
<div class="card"><div>Salves utilisables</div><div class="value">{len(report['bursts'])}</div></div>
<div class="card"><div>Sessions actives</div><div class="value">{report['identifiability']['active_session_count']}</div><small>2 minimum</small></div></div>
<section><h2>Verdict</h2><ul>{gate_rows}</ul><p>{html.escape(report['identifiability']['conclusion'])}</p><p><strong>vehicle_calibration_ready = {str(report['identifiability']['vehicle_calibration_ready']).lower()}</strong></p></section>
<section><h2>Alignement statique commande → lacet</h2><p>Le maximum de corrélation est un alignement apparent, pas un temps de réponse physique.</p><table><thead><tr><th>Décalage ms</th><th>Corrélation</th><th>Gain apparent</th><th>R²</th></tr></thead><tbody>{static_rows}</tbody></table></section>
<section><h2>Modèle dynamique ARX, validation par salve exclue</h2><table><thead><tr><th>Retard ms</th><th>RMSE CV</th><th>Gain vs persistance</th><th>Gain DC apparent</th><th>Constante s</th></tr></thead><tbody>{arx_rows}</tbody></table></section>
<section><h2>Stabilité par salve</h2><table><thead><tr><th>Salve</th><th>Temps</th><th>Durée s</th><th>Vitesse km/h</th><th>Commande effective</th><th>Gain apparent</th><th>R²</th></tr></thead><tbody>{burst_rows}</tbody></table></section>
<section><h2>Utilisation correcte</h2><p>La plage <code>{prior['sensitivity_min']:.4f}…{prior['sensitivity_max']:.4f}</code> peut être balayée dans le HIL. Elle ne doit pas être copiée dans un contrôleur réel. Une identification actionneur exigera une excitation bornée, une mesure indépendante et un protocole d'arrêt validé.</p></section>
<section><h2>Conséquence sur l'enveloppe shadow</h2><p>Avec le prior central, la limite virtuelle ±10 représente seulement environ <code>±{prior['apparent_lateral_accel_at_shadow_limit_10_ms2']:.3f} m/s²</code>. Atteindre numériquement 1,5 m/s² demanderait environ <code>±{prior['apparent_raw_required_for_1_5_ms2']:.1f} raw</code>. La commande usine effective observée couvre <code>{prior['observed_factory_effective_torque_min_raw']:.1f}…{prior['observed_factory_effective_torque_max_raw']:.1f} raw</code>. Cette cohérence explique la saturation du HIL, mais n'autorise pas à relever une limite Panda ou véhicule.</p></section>
</main></body></html>""", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Identifie passivement la relation apparente LKA usine/lacet T9.",
    )
    parser.add_argument("sessions", nargs="+", type=Path)
    parser.add_argument("--dbc", type=Path, default=DEFAULT_DBC)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-factor-raw", type=int, default=90)
    parser.add_argument("--maximum-lag-ms", type=int, default=500)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identification_config = IdentificationConfig(
        minimum_factor_raw=args.minimum_factor_raw,
        maximum_lag_ms=args.maximum_lag_ms,
    )
    simulator_config = SimulatorConfig()
    dbc_path = args.dbc.resolve()
    if not dbc_path.is_file():
        raise SystemExit(f"DBC introuvable : {dbc_path}")

    print("IDENTIFICATION LKA USINE T9 — PASSIVE / HORS LIGNE", flush=True)
    print("Aucun port série, aucune émission CAN, aucune commande véhicule.", flush=True)
    sessions: list[list[ReplaySample]] = []
    session_summaries: list[dict[str, Any]] = []
    for session_path in args.sessions:
        samples, source = load_session_samples(session_path, dbc_path, simulator_config)
        sessions.append(samples)
        active_count = sum(
            1 for sample in samples
            if is_sustained_factory_lka(sample, identification_config)
        )
        session_summaries.append({
            **source,
            "active_samples": active_count,
            "active_duration_s": sum(
                sample.dt_s for sample in samples
                if is_sustained_factory_lka(sample, identification_config)
            ),
            "perception_sample_period_s": statistics.median([
                sample.dt_s for sample in samples if 0.01 <= sample.dt_s <= 0.50
            ]),
        })
        print(f"[session] {source['session_id']}: {active_count} points LKA actifs", flush=True)

    all_samples = [sample for session in sessions for sample in session]
    bursts = split_active_bursts(all_samples, identification_config)
    if len(bursts) < 2:
        raise SystemExit("Pas assez de salves LKA usine indépendantes pour identifier le modèle")
    lag_grid_s = identification_config.lag_grid_ms / 1000.0
    maximum_lag_steps = max(
        0, int(round(args.maximum_lag_ms / (1000.0 * lag_grid_s)))
    )
    static_scan = scan_static_alignment(bursts, maximum_lag_steps, lag_grid_s)
    static_best = max(
        static_scan,
        key=lambda item: abs(float(item["command_response_correlation"])),
    )
    arx_scan = scan_arx_delays(bursts, maximum_lag_steps, lag_grid_s)
    arx_best = min(arx_scan, key=lambda item: float(item["cross_validated_rmse_ms2"]))
    burst_summaries = summarize_bursts(
        bursts, int(static_best["lag_steps"]), lag_grid_s,
    )
    identifiability = build_identifiability_assessment(
        session_summaries, burst_summaries, static_best, arx_best,
    )
    arx_gains = [float(value) for value in arx_best["leave_one_burst_out_dc_gains"]]
    effective_commands = [
        effective_factory_torque_raw(sample) for burst in bursts for sample in burst
    ]
    central_gain = statistics.median(arx_gains)
    prior = {
        "purpose": "hil_sensitivity_only",
        "central_gain_ms2_per_effective_raw": central_gain,
        "sensitivity_min": min(arx_gains),
        "sensitivity_max": max(arx_gains),
        "observed_factory_effective_torque_min_raw": min(effective_commands),
        "observed_factory_effective_torque_max_raw": max(effective_commands),
        "apparent_lateral_accel_at_shadow_limit_10_ms2": central_gain * 10.0,
        "apparent_raw_required_for_1_5_ms2": 1.5 / central_gain,
        "selected_arx_delay_ms": arx_best["delay_ms"],
        "static_peak_alignment_ms": static_best["lag_ms"],
        "physical_delay_validated": False,
        "vehicle_parameter": False,
    }
    active_session_count = int(identifiability["active_session_count"])
    if active_session_count < 2:
        session_limitation = (
            f"Seulement {active_session_count} session contient du LKA usine actif."
        )
    elif not identifiability["gates"]["session_median_gain_spread_below_15_percent"]:
        session_limitation = (
            f"Les {active_session_count} sessions LKA actives présentent une dispersion "
            f"relative des gains médians de "
            f"{100.0 * identifiability['session_gain_relative_spread']:.1f} %, "
            "au-dessus du seuil de 15 %."
        )
    else:
        session_limitation = (
            f"Le LKA usine actif est observé dans {active_session_count} sessions; "
            "la reproductibilité inter-session passe le seuil configuré."
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        args.output
        or DEFAULT_OUTPUT_ROOT / f"factory-lka-identification-{timestamp}"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = _round({
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_passive_closed_loop_identification",
        "vehicle_control_supported": False,
        "dbc": str(dbc_path),
        "config": asdict(identification_config),
        "lag_grid_s": lag_grid_s,
        "sessions": session_summaries,
        "active_samples": sum(len(burst) for burst in bursts),
        "bursts": burst_summaries,
        "static_best_alignment": static_best,
        "static_alignment_scan": static_scan,
        "dynamic_arx_best": arx_best,
        "dynamic_arx_delay_scan": arx_scan,
        "simulation_prior": prior,
        "identifiability": identifiability,
        "limitations": [
            "Une commande de boucle fermée corrélée à la courbe n'est pas une excitation indépendante.",
            "Le couple conducteur et la commande LKA ne sont pas expérimentalement orthogonaux.",
            session_limitation,
            "Le décalage de corrélation ne doit pas être interprété comme une latence EPS.",
            "Le gain apparent reste réservé au balayage de sensibilité HIL.",
        ],
        "artifacts": {
            "report_html": "report.html",
            "report_json": "report.json",
            "active_samples_csv": "active_samples.csv",
            "bursts_csv": "bursts.csv",
        },
    })
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_active_csv(output_dir / "active_samples.csv", bursts)
    _write_bursts_csv(output_dir / "bursts.csv", report["bursts"])
    _write_html(output_dir / "report.html", report)
    print(
        f"[prior HIL] {prior['central_gain_ms2_per_effective_raw']:.5f} "
        f"({prior['sensitivity_min']:.5f}..{prior['sensitivity_max']:.5f}) m/s²/raw",
        flush=True,
    )
    print(
        f"[retards] alignement statique={static_best['lag_ms']:.0f} ms, "
        f"ARX CV={arx_best['delay_ms']:.0f} ms — latence physique non validée",
        flush=True,
    )
    print(f"[rapport] {output_dir / 'report.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
