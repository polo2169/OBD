import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { api } from "../api";
import type {
  TelecodingBackupSummary,
  TelecodingCatalogResult,
  TelecodingChangeRequest,
  TelecodingExecuteResult,
  TelecodingPreviewResult,
  TelecodingSnapshotResult,
} from "../types";

type LabChecks = {
  vehicle_stationary: boolean;
  ignition_on_engine_off: boolean;
  stable_battery_voltage: boolean;
  workshop_or_private_site: boolean;
};

type TelecodingWorkspaceProps = {
  ecuKey: string;
  readReady: boolean;
  writeEnabled: boolean;
  securityAccessEnabled: boolean;
  readOnly: boolean;
  labChecksComplete: boolean;
  labChecks: LabChecks;
  effectiveLabChecks: LabChecks;
  lockedChecks: Pick<LabChecks, "vehicle_stationary" | "ignition_on_engine_off" | "stable_battery_voltage">;
  setLabChecks: Dispatch<SetStateAction<LabChecks>>;
};

function displayDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("fr-FR");
}

export function TelecodingWorkspace({
  ecuKey,
  readReady,
  writeEnabled,
  securityAccessEnabled,
  readOnly,
  labChecksComplete,
  labChecks,
  effectiveLabChecks,
  lockedChecks,
  setLabChecks,
}: TelecodingWorkspaceProps) {
  const [catalog, setCatalog] = useState<TelecodingCatalogResult | null>(null);
  const [variantId, setVariantId] = useState("");
  const [didHex, setDidHex] = useState("");
  const [search, setSearch] = useState("");
  const [writableOnly, setWritableOnly] = useState(true);
  const [snapshot, setSnapshot] = useState<TelecodingSnapshotResult | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<TelecodingPreviewResult | null>(null);
  const [execution, setExecution] = useState<TelecodingExecuteResult | null>(null);
  const [backups, setBackups] = useState<TelecodingBackupSummary[]>([]);
  const [applicationKey, setApplicationKey] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState<"catalog" | "read" | "preview" | "execute" | "backup" | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setBusy("catalog");
    setError("");
    setCatalog(null);
    setVariantId("");
    setDidHex("");
    setSnapshot(null);
    setDraft({});
    setPreview(null);
    setExecution(null);
    Promise.all([
      api<TelecodingCatalogResult>(`/api/diagnostic/psa/ecus/${encodeURIComponent(ecuKey)}/telecoding/catalog`),
      api<TelecodingBackupSummary[]>(`/api/diagnostic/psa/telecoding/backups?ecu_key=${encodeURIComponent(ecuKey)}`),
    ]).then(([nextCatalog, nextBackups]) => {
      if (cancelled) return;
      setCatalog(nextCatalog);
      setBackups(nextBackups);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (!cancelled) setBusy("");
    });
    return () => { cancelled = true; };
  }, [ecuKey]);

  const variant = catalog?.variants.find((item) => item.id === variantId) ?? null;
  const codingZones = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("fr");
    return (variant?.zones ?? []).filter((zone) => {
      if (!zone.coding_candidate || (writableOnly && !zone.writable)) return false;
      if (!query) return true;
      return `${zone.did_hex} ${zone.name} ${zone.tab_name}`.toLocaleLowerCase("fr").includes(query);
    });
  }, [variant, search, writableOnly]);
  const selectedZone = variant?.zones.find((zone) => zone.did_hex === didHex) ?? null;
  const changes: TelecodingChangeRequest[] = Object.entries(draft).map(([field_key, option_key]) => ({
    field_key,
    option_key,
  }));
  const expectedConfirmation = didHex ? `TELECODER ${ecuKey.toUpperCase()} ${didHex}` : "";
  const writeRuntimeReady = writeEnabled && securityAccessEnabled && !readOnly;

  function resetZoneState(nextDid = "") {
    setDidHex(nextDid);
    setSnapshot(null);
    setDraft({});
    setPreview(null);
    setExecution(null);
    setConfirmation("");
    setError("");
  }

  function selectVariant(nextVariantId: string) {
    setVariantId(nextVariantId);
    setApplicationKey("");
    resetZoneState();
  }

  async function readAndBackupZone() {
    if (!variant || !selectedZone) return;
    setBusy("read");
    setError("");
    try {
      const result = await api<TelecodingSnapshotResult>(
        `/api/diagnostic/psa/ecus/${encodeURIComponent(ecuKey)}/telecoding/snapshots`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ variant_id: variant.id, did: selectedZone.did }),
        },
      );
      setSnapshot(result);
      setDraft({});
      setPreview(null);
      setExecution(null);
      setBackups((current) => [{
        snapshot_id: result.snapshot_id,
        captured_at: result.captured_at,
        ecu_key: result.ecu_key,
        variant_id: result.variant_id,
        did: result.did,
        did_hex: result.did_hex,
        zone_name: result.zone_name,
        vin: result.vin,
        sha256: result.sha256,
        raw_length: result.raw_hex.length / 2,
      }, ...current.filter((item) => item.snapshot_id !== result.snapshot_id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  async function openBackup(summary: TelecodingBackupSummary) {
    setBusy("backup");
    setError("");
    try {
      const result = await api<TelecodingSnapshotResult>(
        `/api/diagnostic/psa/telecoding/backups/${encodeURIComponent(summary.snapshot_id)}`,
      );
      if (!catalog?.variants.some((item) => item.id === result.variant_id)) {
        throw new Error("La variante de cette sauvegarde n'existe plus dans le catalogue chargé.");
      }
      setVariantId(result.variant_id);
      setDidHex(result.did_hex);
      setSnapshot(result);
      setDraft({});
      setPreview(null);
      setExecution(null);
      setApplicationKey("");
      setConfirmation("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  function changeField(fieldKey: string, optionKey: string, currentOptionKey?: string | null) {
    setDraft((current) => {
      const next = { ...current };
      if (!optionKey || optionKey === currentOptionKey) delete next[fieldKey];
      else next[fieldKey] = optionKey;
      return next;
    });
    setPreview(null);
    setExecution(null);
    setConfirmation("");
  }

  async function buildPreview() {
    if (!snapshot || changes.length === 0) return;
    setBusy("preview");
    setError("");
    try {
      const result = await api<TelecodingPreviewResult>("/api/diagnostic/psa/telecoding/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: snapshot.snapshot_id, changes }),
      });
      setPreview(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  async function executePlan() {
    if (!snapshot || !preview) return;
    setBusy("execute");
    setError("");
    try {
      const result = await api<TelecodingExecuteResult>("/api/diagnostic/psa/telecoding/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          snapshot_id: snapshot.snapshot_id,
          changes,
          plan_hash: preview.plan_hash,
          application_key_hex: applicationKey,
          confirmation,
          ...effectiveLabChecks,
        }),
      });
      setExecution(result);
      setConfirmation("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  function updateCheck(key: keyof LabChecks, checked: boolean) {
    setLabChecks((current) => ({ ...current, [key]: checked }));
  }

  return (
    <section className="panel telecoding-workspace">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Atelier PyPSADiag · lecture, sauvegarde, diff, écriture, contrôle</span>
          <h2>Télécodage structuré</h2>
          <p>Chaque opération cible une variante et une zone exactes. Le backend relit l’ECU juste avant l’écriture et annule si la sauvegarde est devenue obsolète.</p>
        </div>
        <span className={`status-pill ${writeRuntimeReady ? "warning" : catalog?.variants.length ? "good" : "neutral"}`}>
          <i /> {writeRuntimeReady ? "Écriture armable" : catalog?.variants.length ? "Lecture & préparation" : "Sans définition"}
        </span>
      </div>

      <div className="telecoding-steps" aria-label="Étapes du télécodage">
        <span className={variant ? "complete" : ""}><b>1</b> Variante</span>
        <span className={snapshot ? "complete" : ""}><b>2</b> Sauvegarde</span>
        <span className={preview?.executable ? "complete" : ""}><b>3</b> Diff validé</span>
        <span className={execution?.verified ? "complete" : ""}><b>4</b> Relecture</span>
      </div>

      {error && <p className="telecoding-error" role="alert">{error}</p>}
      {catalog && <p className="inline-alert">{catalog.warning} Source {catalog.source} · révision {catalog.revision?.slice(0, 12) ?? "—"} · {catalog.license ?? "licence inconnue"}.</p>}

      <div className="telecoding-selector-grid">
        <label>Variante ECU confirmée
          <select value={variantId} onChange={(event) => selectVariant(event.target.value)}>
            <option value="">Choisir explicitement la variante…</option>
            {catalog?.variants.map((item) => (
              <option key={item.id} value={item.id}>{item.name} · {item.protocol.toUpperCase()} · {item.writable_zone_count} zone(s) écrivable(s)</option>
            ))}
          </select>
        </label>
        <label>Recherche dans les zones
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="DID, fonction, catégorie…" disabled={!variant} />
        </label>
        <label className="telecoding-toggle"><input type="checkbox" checked={writableOnly} onChange={(event) => setWritableOnly(event.target.checked)} /> Afficher uniquement les zones éditables</label>
      </div>

      {variant && (
        <div className="telecoding-variant-summary">
          <div><span>Adresse</span><strong>0x{variant.request_id?.toString(16).toUpperCase()} → 0x{variant.response_id?.toString(16).toUpperCase()}</strong></div>
          <div><span>Catalogue</span><strong>{variant.coding_zone_count} zones de configuration</strong></div>
          <div><span>Clés documentées</span><strong>{variant.security_keys.length || "Aucune"}</strong></div>
          <div><span>Écriture</span><strong>{variant.write_supported ? "UDS prise en charge" : "Consultation seulement"}</strong></div>
        </div>
      )}

      {variant && (
        <div className="telecoding-browser">
          <aside className="telecoding-zone-list">
            <header><strong>{codingZones.length} zone(s)</strong><small>{writableOnly ? "éditables" : "cataloguées"}</small></header>
            {codingZones.slice(0, 250).map((zone) => (
              <button className={didHex === zone.did_hex ? "active" : ""} key={zone.did_hex} onClick={() => resetZoneState(zone.did_hex)}>
                <code>0x{zone.did_hex}</code><span>{zone.name}</span><small>{zone.tab_name} · {zone.fields.length} champ(s)</small>
              </button>
            ))}
            {codingZones.length > 250 && <p>Affinez la recherche pour afficher les {codingZones.length - 250} autres zones.</p>}
          </aside>

          <div className="telecoding-editor">
            {!selectedZone ? <div className="telecoding-placeholder"><strong>Sélectionnez une zone</strong><span>La lecture est toujours enregistrée avant qu’un champ puisse être modifié.</span></div> : (
              <>
                <div className="telecoding-zone-heading">
                  <div><code>0x{selectedZone.did_hex}</code><h3>{selectedZone.name}</h3><span>{selectedZone.tab_name}</span></div>
                  <button className="primary-button" onClick={() => void readAndBackupZone()} disabled={!readReady || busy === "read"}>{busy === "read" ? "Lecture et sauvegarde…" : snapshot ? "Relire et créer une nouvelle sauvegarde" : "Lire et sauvegarder avant modification"}</button>
                </div>
                {!snapshot && <p className="inline-alert">Aucune valeur du catalogue n’est présélectionnée sans réponse du véhicule. La longueur et les champs disponibles seront contrôlés après lecture.</p>}
                {snapshot && (
                  <>
                    <div className="telecoding-backup-proof">
                      <div><span>Sauvegarde</span><strong>{snapshot.snapshot_id}</strong></div>
                      <div><span>VIN</span><strong>{snapshot.vin ?? "non associé — écriture impossible"}</strong></div>
                      <div><span>Empreinte SHA-256</span><code>{snapshot.sha256}</code></div>
                      <div><span>Valeur brute</span><code>{snapshot.raw_hex}</code></div>
                    </div>
                    <div className="telecoding-fields">
                      {snapshot.fields.map((field) => (
                        <article className={`${field.writable ? "writable" : "readonly"} ${draft[field.key] ? "changed" : ""}`} key={field.key}>
                          <div><span>Octet {field.byte}{field.byte_length > 1 ? ` · ${field.byte_length} octets` : ""}</span><strong>{field.name}</strong><small>{field.available ? `Actuel : ${field.value ?? "non décodé"}` : "Indisponible pour cette longueur de zone"}</small></div>
                          {field.writable && field.available ? (
                            <select value={draft[field.key] ?? field.value_key ?? ""} onChange={(event) => changeField(field.key, event.target.value, field.value_key)}>
                              {!field.value_key && <option value="">Valeur actuelle inconnue</option>}
                              {field.options.map((option) => <option value={option.key} key={option.key}>{option.name}</option>)}
                            </select>
                          ) : <span className="telecoding-readonly">Lecture seule</span>}
                        </article>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {snapshot && changes.length > 0 && (
        <div className="telecoding-plan">
          <div className="section-heading"><div><span className="eyebrow">Simulation locale · aucune émission</span><h3>Plan de modification</h3><p>{changes.length} champ(s) modifié(s) dans une seule écriture de zone.</p></div><button className="secondary-button" onClick={() => void buildPreview()} disabled={busy === "preview"}>{busy === "preview" ? "Calcul…" : "Calculer et verrouiller le diff"}</button></div>
          {preview && (
            <div className={`telecoding-diff ${preview.executable ? "ready" : "blocked"}`}>
              <div><span>Avant</span><code>{preview.raw_before_hex}</code></div>
              <div><span>Après</span><code>{preview.raw_after_hex}</code></div>
              <p>Octets modifiés : {preview.changed_byte_indexes.join(", ") || "aucun"} · plan <code>{preview.plan_hash.slice(0, 16)}…</code></p>
              {preview.changes.map((change) => <p key={change.field_key}><strong>{change.field_name}</strong> : {change.previous_value ?? "inconnu"} → {change.requested_value}</p>)}
              {preview.blockers.map((blocker) => <p className="telecoding-error" key={blocker}>{blocker}</p>)}
            </div>
          )}
        </div>
      )}

      {preview?.executable && (
        <div className="telecoding-execution-gate">
          <h3>Autorisation finale</h3>
          <div className="dtc-clear-checks">
            <label><input type="checkbox" disabled={lockedChecks.vehicle_stationary} checked={effectiveLabChecks.vehicle_stationary} onChange={(event) => updateCheck("vehicle_stationary", event.target.checked)} /> Véhicule immobilisé</label>
            <label><input type="checkbox" disabled={lockedChecks.ignition_on_engine_off} checked={effectiveLabChecks.ignition_on_engine_off} onChange={(event) => updateCheck("ignition_on_engine_off", event.target.checked)} /> Contact mis, moteur arrêté</label>
            <label><input type="checkbox" disabled={lockedChecks.stable_battery_voltage} checked={effectiveLabChecks.stable_battery_voltage} onChange={(event) => updateCheck("stable_battery_voltage", event.target.checked)} /> Tension batterie stable</label>
            <label><input type="checkbox" checked={labChecks.workshop_or_private_site} onChange={(event) => updateCheck("workshop_or_private_site", event.target.checked)} /> Atelier ou site privé</label>
          </div>
          <div className="telecoding-final-form">
            <label>Clé correspondant à la variante<select value={applicationKey} onChange={(event) => setApplicationKey(event.target.value)}><option value="">Choisir la clé confirmée…</option>{variant?.security_keys.map((key) => <option key={`${key.variant}-${key.key_hex}`} value={key.key_hex}>{key.variant} · {key.key_hex}</option>)}</select></label>
            <label>Confirmation exacte<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={expectedConfirmation} /><small>{expectedConfirmation}</small></label>
            <button className="danger-button" onClick={() => void executePlan()} disabled={!writeRuntimeReady || !readReady || !labChecksComplete || !applicationKey || confirmation !== expectedConfirmation || busy === "execute"}>{busy === "execute" ? "Relecture, écriture et contrôle…" : "Écrire une fois puis relire"}</button>
          </div>
          {!writeRuntimeReady && <p className="inline-alert">Double verrou actif : mode Maintenance contrôlée, `PSA_TELECODING_WRITE_ENABLED=true` et `PSA_SECURITY_ACCESS_ENABLED=true` sont requis.</p>}
        </div>
      )}

      {execution && <div className={`telecoding-execution-result ${execution.verified ? "verified" : "warning"}`}><strong>{execution.verified ? "Télécodage vérifié" : "Contrôle divergent"}</strong><span>{execution.message}</span><code>{execution.raw_before_hex} → {execution.raw_after_hex ?? "—"}</code><small>Rapport {execution.execution_id} · trace {execution.session_id ?? "—"}</small></div>}

      <details className="telecoding-history">
        <summary>Sauvegardes locales de ce calculateur ({backups.length})</summary>
        <div>{backups.slice(0, 20).map((backup) => <button key={backup.snapshot_id} onClick={() => void openBackup(backup)} disabled={busy === "backup"}><code>0x{backup.did_hex}</code><span>{backup.zone_name}</span><small>{displayDate(backup.captured_at)} · {backup.vin ?? "sans VIN"} · {backup.raw_length} octet(s)</small></button>)}</div>
      </details>
    </section>
  );
}
