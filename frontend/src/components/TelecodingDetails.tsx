import type { TelecodingZoneInfo } from "../types";

export function TelecodingDetails({ zone }: { zone: TelecodingZoneInfo }) {
  return (
    <div className="telecoding-details">
      <p className="telecoding-heading">{zone.name} <small>· famille {zone.family} · {zone.confidence}</small></p>
      {zone.parameters.length === 0 ? (
        <p className="inline-alert">Aucun paramètre de télécodage documenté pour cette valeur.</p>
      ) : (
        <ul className="telecoding-parameter-list">
          {zone.parameters.map((param) => (
            <li key={param.key}>
              <code>{param.raw_hex}</code>
              <span>{param.name}</span>
              <strong>{param.value ?? "valeur non répertoriée"}</strong>
            </li>
          ))}
        </ul>
      )}
      {zone.source && <small>Source : {zone.source} (communauté, non vérifié sur ce véhicule)</small>}
    </div>
  );
}
