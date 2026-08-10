import { replayGaugeCatalog } from "../replay";
import type { ReplaySample, ReplayValidation } from "../types";

export function ExperimentalSignalsPanel({
  point,
  validation,
  onValidate,
  onClear,
  busyKey,
}: {
  point: ReplaySample | null;
  validation?: ReplayValidation | null;
  onValidate?: (key: string, validated: boolean) => void;
  onClear?: (key: string) => void;
  busyKey?: string;
}) {
  const definitions = replayGaugeCatalog.filter((definition) => definition.experimental);
  if (!point) return null;
  return (
    <section className="panel experimental-signals-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">En cours de validation</span>
          <h2>Signaux expérimentaux</h2>
          <p>Candidats trouvés par corrélation, pas encore confirmés officiellement.{onValidate ? " Valeur en direct et confirmation manuelle ci-dessous." : " Valeur en direct pendant le test."}</p>
        </div>
      </div>
      <div className="experimental-signal-list">
        {definitions.map((definition) => {
          const raw = point[definition.key];
          const value = typeof raw === "number"
            ? `${raw.toFixed(definition.precision ?? 0)} ${definition.unit}`
            : typeof raw === "boolean"
              ? (raw ? "Actif" : "Inactif")
              : "—";
          const signal = validation?.signals.find((item) => item.key === definition.key);
          return (
            <article key={definition.key}>
              <div><strong>{definition.label}</strong><small>{definition.note}</small></div>
              <div className="experimental-signal-value">{value}</div>
              {signal && <span className={`validation-badge ${signal.status}`}>{signal.status === "validated" ? "Validé" : signal.status === "plausible" ? "Plausible" : signal.status === "suspicious" ? "Suspect" : signal.status === "unavailable" ? "Indisponible" : "À confirmer"}</span>}
              {onValidate && onClear && signal && signal.status !== "unavailable" && (
                <div className="validation-manual-actions">
                  {signal.manual_validation === true ? (
                    <>
                      <span className="manual-validation-tag confirmed">Confirmé</span>
                      <button className="ghost-button" disabled={busyKey === definition.key} onClick={() => onClear(definition.key)}>Retirer</button>
                    </>
                  ) : signal.manual_validation === false ? (
                    <>
                      <span className="manual-validation-tag rejected">Invalidé</span>
                      <button className="ghost-button" disabled={busyKey === definition.key} onClick={() => onClear(definition.key)}>Retirer</button>
                    </>
                  ) : (
                    <>
                      <button className="secondary-button" disabled={busyKey === definition.key} onClick={() => onValidate(definition.key, true)}>Confirmer</button>
                      <button className="ghost-button" disabled={busyKey === definition.key} onClick={() => onValidate(definition.key, false)}>Invalide</button>
                    </>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
