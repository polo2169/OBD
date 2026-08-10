import { EmptyState } from "../components/ui";
import type { BehavioralAnalysis, SignalCandidate } from "../types";

type AnalysisScreenProps = {
  analysis: BehavioralAnalysis | null;
  onAnalyze: (sessionId: string) => Promise<void>;
  formatDuration: (milliseconds: number) => string;
  formatHexadecimal: (value: number | null | undefined) => string;
  candidateLocation: (candidate: SignalCandidate) => string;
};

export function AnalysisScreen({
  analysis,
  onAnalyze,
  formatDuration,
  formatHexadecimal,
  candidateLocation,
}: AnalysisScreenProps) {
  if (!analysis) return null;

  return (
    <section className="analysis-stack">
      <article className="panel analysis-summary">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Rapport sauvegardé</span>
            <h2>Résultats du post-traitement</h2>
          </div>
          <button className="secondary-button" onClick={() => void onAnalyze(analysis.session_id)}>
            Recalculer
          </button>
        </div>
        <div className="compact-metrics">
          <div><span>Trames</span><strong>{analysis.total_frames.toLocaleString("fr-FR")}</strong></div>
          <div><span>Identifiants</span><strong>{analysis.unique_ids}</strong></div>
          <div><span>Marqueurs</span><strong>{analysis.marker_count}</strong></div>
          <div><span>Durée</span><strong>{formatDuration(analysis.duration_ms)}</strong></div>
        </div>
        {analysis.opendbc && (
          <div className={`opendbc-strip ${analysis.opendbc.loaded ? "loaded" : "unavailable"}`}>
            <span>OPENDBC</span>
            <div>
              <strong>{analysis.opendbc.database}</strong>
              <small>{analysis.opendbc.loaded ? `${analysis.opendbc.message_count} messages · ${analysis.opendbc.signal_count} signaux` : analysis.opendbc.error}</small>
            </div>
            <div><small>Messages reconnus</small><strong>{analysis.opendbc.observed_message_count}</strong></div>
            <div><small>Trames décodées</small><strong>{analysis.opendbc.decoded_frame_count.toLocaleString("fr-FR")}</strong></div>
            <a href={analysis.opendbc.source_url} target="_blank" rel="noreferrer">Source ↗</a>
          </div>
        )}
        {analysis.warnings.map((warning) => <p className="inline-alert" key={warning}>{warning}</p>)}
      </article>

      {analysis.correlations.map((correlation) => (
        <article className="panel" key={correlation.marker}>
          <div className="section-heading correlation-heading">
            <div>
              <span className="eyebrow">{correlation.occurrences} occurrence(s)</span>
              <h2>{correlation.marker}</h2>
              <p>Fenêtres −{correlation.before_ms} ms / +{correlation.after_ms} ms</p>
            </div>
            <span className="candidate-count">{correlation.candidates.length} hypothèses</span>
          </div>
          {correlation.notes.length > 0 && <p className="notes">{correlation.notes.join(" · ")}</p>}
          {correlation.candidates.length === 0 ? (
            <EmptyState title="Pas de signal assez stable" text="Répète l'action trois fois ou augmente la durée de capture avant et après le marqueur." />
          ) : (
            <div className="candidate-list">
              {correlation.candidates.map((candidate, index) => (
                <div className="candidate-row" key={`${candidateLocation(candidate)}-${candidate.kind}-${index}`}>
                  <div className="candidate-rank">{String(index + 1).padStart(2, "0")}</div>
                  <div className="candidate-main">
                    <div>
                      <code>{candidateLocation(candidate)}</code>
                      <span className="kind-tag">{candidate.kind === "dbc_signal" ? "signal DBC" : candidate.kind}</span>
                      {candidate.source === "opendbc" && <span className="source-tag">opendbc</span>}
                    </div>
                    <strong>{candidate.before_value} <b>→</b> {candidate.after_value}</strong>
                    <small>{candidate.rationale[0]}</small>
                  </div>
                  <div className="score-box">
                    <span className={`confidence ${candidate.confidence}`}>{candidate.confidence}</span>
                    <strong>{Math.round(candidate.score * 100)}%</strong>
                    <div className="score-track"><i style={{ width: `${candidate.score * 100}%` }} /></div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </article>
      ))}

      <article className="panel">
        <div className="section-heading">
          <div><span className="eyebrow">Cartographie passive</span><h2>Inventaire CAN</h2></div>
        </div>
        <div className="inventory-table">
          <div className="inventory-head"><span>ID</span><span>Trames</span><span>Fréquence</span><span>DLC</span><span>Octets variables</span><span>opendbc</span></div>
          {analysis.inventory.map((profile) => (
            <div className="inventory-row" key={`${profile.arbitration_id}-${profile.extended}`}>
              <code>{formatHexadecimal(profile.arbitration_id)}</code>
              <span>{profile.frame_count.toLocaleString("fr-FR")}</span>
              <span>{profile.frequency_hz.toFixed(1)} Hz</span>
              <span>{Object.entries(profile.dlc_counts).map(([dlc, count]) => `${dlc}×${count}`).join(" · ")}</span>
              <strong>{profile.changing_bytes.length ? profile.changing_bytes.join(", ") : "stables"}</strong>
              <span className={profile.opendbc_message ? "known-message" : "unknown-message"} title={profile.opendbc_signals.join(", ")}>
                {profile.opendbc_message ?? "inconnu"}
              </span>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
