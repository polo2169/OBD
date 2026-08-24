import { useMemo, useState } from "react";

import { API_BASE } from "../api";
import { EmptyState } from "./ui";
import type {
  DiagnosticVehicle,
  MaintenanceInvoiceAnalysis,
  MaintenanceMileageEstimate,
  MaintenancePart,
  MaintenanceRecord,
  MaintenanceRecordInput,
} from "../types";


type MaintenanceHistoryPanelProps = {
  vehicle: DiagnosticVehicle | null;
  records: MaintenanceRecord[];
  liveOdometerKm: number | null;
  busy: boolean;
  onCreate: (entry: MaintenanceRecordInput, documents: File[]) => Promise<boolean>;
  onAddDocuments: (recordId: string, documents: File[]) => Promise<void>;
  onEstimateMileage: (vin: string, performedAt: string) => Promise<MaintenanceMileageEstimate | null>;
  onAnalyzeInvoice: (vin: string, document: File) => Promise<MaintenanceInvoiceAnalysis | null>;
};

type PartDraft = {
  name: string;
  manufacturer: string;
  part_number: string;
  serial_number: string;
  removed_part_number: string;
  removed_serial_number: string;
  quantity: string;
  unit_price: string;
  warranty_until: string;
  note: string;
};

const emptyPart = (): PartDraft => ({
  name: "",
  manufacturer: "",
  part_number: "",
  serial_number: "",
  removed_part_number: "",
  removed_serial_number: "",
  quantity: "1",
  unit_price: "",
  warranty_until: "",
  note: "",
});

const partDraftFromAnalysis = (part: MaintenancePart): PartDraft => ({
  name: part.name,
  manufacturer: part.manufacturer ?? "",
  part_number: part.part_number ?? "",
  serial_number: part.serial_number ?? "",
  removed_part_number: part.removed_part_number ?? "",
  removed_serial_number: part.removed_serial_number ?? "",
  quantity: String(part.quantity),
  unit_price: typeof part.unit_price === "number" ? String(part.unit_price) : "",
  warranty_until: part.warranty_until ?? "",
  note: part.note ?? "",
});

const today = () => {
  const current = new Date();
  const local = new Date(current.getTime() - current.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
};

const optionalNumber = (value: string) => value.trim() ? Number(value) : null;
const formatMoney = (value: number, currency: string) => new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency,
}).format(value);

export function MaintenanceHistoryPanel({
  vehicle,
  records,
  liveOdometerKm,
  busy,
  onCreate,
  onAddDocuments,
  onEstimateMileage,
  onAnalyzeInvoice,
}: MaintenanceHistoryPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [performedAt, setPerformedAt] = useState(today);
  const [mileageKm, setMileageKm] = useState("");
  const [mileageSource, setMileageSource] = useState<MaintenanceRecordInput["mileage_source"]>("manual");
  const [mileageHint, setMileageHint] = useState("");
  const [mileageBusy, setMileageBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("Entretien courant");
  const [workshop, setWorkshop] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceTotal, setInvoiceTotal] = useState("");
  const [laborHours, setLaborHours] = useState("");
  const [notes, setNotes] = useState("");
  const [parts, setParts] = useState<PartDraft[]>([emptyPart()]);
  const [documents, setDocuments] = useState<File[]>([]);
  const [invoiceAnalysis, setInvoiceAnalysis] = useState<MaintenanceInvoiceAnalysis | null>(null);
  const [invoiceBusy, setInvoiceBusy] = useState(false);
  const [pendingDocuments, setPendingDocuments] = useState<Record<string, File[]>>({});
  const [formError, setFormError] = useState("");

  const sortedRecords = useMemo(
    () => [...records].sort((left, right) => (
      right.performed_at.localeCompare(left.performed_at)
      || right.updated_at.localeCompare(left.updated_at)
    )),
    [records],
  );
  const totalSpent = records.reduce((sum, record) => sum + (record.invoice_total ?? 0), 0);
  const partCount = records.reduce((sum, record) => sum + record.parts.length, 0);

  function updatePart(index: number, key: keyof PartDraft, value: string) {
    setParts((current) => current.map((part, partIndex) => (
      partIndex === index ? { ...part, [key]: value } : part
    )));
  }

  function resetForm() {
    setPerformedAt(today());
    setMileageKm("");
    setMileageSource("manual");
    setMileageHint("");
    setTitle("");
    setCategory("Entretien courant");
    setWorkshop("");
    setInvoiceNumber("");
    setInvoiceTotal("");
    setLaborHours("");
    setNotes("");
    setParts([emptyPart()]);
    setDocuments([]);
    setInvoiceAnalysis(null);
    setFormError("");
    setExpanded(false);
  }

  async function estimateMileageForDate(dateValue: string) {
    if (!vehicle || !dateValue) return;
    if (dateValue === today() && liveOdometerKm !== null) {
      const mileage = Math.round(liveOdometerKm);
      setMileageKm(String(mileage));
      setMileageSource("can_signal");
      setMileageHint(`Lecture CAN actuelle : ${mileage.toLocaleString("fr-FR")} km.`);
      return;
    }
    setMileageBusy(true);
    try {
      const estimate = await onEstimateMileage(vehicle.vin, dateValue);
      if (!estimate) return;
      setMileageHint(estimate.message);
      if (typeof estimate.mileage_km === "number") {
        setMileageKm(String(estimate.mileage_km));
        setMileageSource("history_estimate");
      }
    } finally {
      setMileageBusy(false);
    }
  }

  async function analyzeSelectedInvoice() {
    if (!vehicle || !documents.length) return;
    setInvoiceBusy(true);
    setFormError("");
    try {
      const analysis = await onAnalyzeInvoice(vehicle.vin, documents[0]);
      if (!analysis) return;
      setInvoiceAnalysis(analysis);
      const detectedDate = analysis.performed_at || performedAt;
      if (analysis.performed_at) setPerformedAt(analysis.performed_at);
      if (analysis.title) setTitle(analysis.title);
      if (analysis.category) setCategory(analysis.category);
      if (analysis.workshop) setWorkshop(analysis.workshop);
      if (analysis.invoice_number) setInvoiceNumber(analysis.invoice_number);
      if (typeof analysis.invoice_total === "number") setInvoiceTotal(String(analysis.invoice_total));
      if (analysis.parts.length) setParts(analysis.parts.map(partDraftFromAnalysis));
      if (typeof analysis.mileage_km === "number") {
        setMileageKm(String(analysis.mileage_km));
        setMileageSource("invoice");
        setMileageHint(`Kilométrage lu sur la facture : ${analysis.mileage_km.toLocaleString("fr-FR")} km.`);
      } else if (detectedDate) {
        await estimateMileageForDate(detectedDate);
      }
    } finally {
      setInvoiceBusy(false);
    }
  }

  async function handleSubmit() {
    if (!vehicle) return;
    const mileage = Number(mileageKm);
    if (!title.trim()) {
      setFormError("Indique le nom de l’intervention.");
      return;
    }
    if (!Number.isInteger(mileage) || mileage < 0) {
      setFormError("Le kilométrage doit être un nombre entier positif.");
      return;
    }
    const normalizedParts: MaintenancePart[] = [];
    for (const part of parts) {
      if (!part.name.trim()) continue;
      const quantity = Number(part.quantity);
      const unitPrice = optionalNumber(part.unit_price);
      if (!Number.isFinite(quantity) || quantity <= 0 || (unitPrice !== null && !Number.isFinite(unitPrice))) {
        setFormError("Vérifie la quantité et le prix des pièces.");
        return;
      }
      normalizedParts.push({
        name: part.name.trim(),
        manufacturer: part.manufacturer.trim() || null,
        part_number: part.part_number.trim() || null,
        serial_number: part.serial_number.trim() || null,
        removed_part_number: part.removed_part_number.trim() || null,
        removed_serial_number: part.removed_serial_number.trim() || null,
        quantity,
        unit_price: unitPrice,
        warranty_until: part.warranty_until || null,
        note: part.note.trim() || null,
      });
    }
    const total = optionalNumber(invoiceTotal);
    const labor = optionalNumber(laborHours);
    if ((total !== null && (!Number.isFinite(total) || total < 0)) || (labor !== null && (!Number.isFinite(labor) || labor < 0))) {
      setFormError("Vérifie le montant de facture et le temps de main-d’œuvre.");
      return;
    }
    const saved = await onCreate({
      vin: vehicle.vin,
      vehicle_profile: vehicle.vehicle_profile,
      performed_at: performedAt,
      mileage_km: mileage,
      mileage_source: mileageSource,
      mileage_note: mileageSource === "manual" ? null : mileageHint || null,
      title: title.trim(),
      category,
      workshop: workshop.trim() || null,
      invoice_number: invoiceNumber.trim() || null,
      invoice_total: total,
      currency: "EUR",
      labor_hours: labor,
      notes: notes.trim() || null,
      parts: normalizedParts,
    }, documents);
    if (saved) resetForm();
  }

  return (
    <section className="panel maintenance-history-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Dossier mécanique par VIN</span>
          <h2>Historique des interventions</h2>
          <p>Factures, pièces, références et numéros de série restent rattachés au véhicule sélectionné.</p>
        </div>
        <button className="primary-button" disabled={!vehicle} onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Fermer le formulaire" : "＋ Ajouter une intervention"}
        </button>
      </div>

      <div className="maintenance-history-metrics">
        <article><span>Interventions</span><strong>{records.length}</strong></article>
        <article><span>Pièces enregistrées</span><strong>{partCount}</strong></article>
        <article><span>Factures jointes</span><strong>{records.reduce((sum, record) => sum + record.documents.length, 0)}</strong></article>
        <article><span>Total documenté</span><strong>{formatMoney(totalSpent, "EUR")}</strong></article>
      </div>

      {!vehicle && <p className="inline-alert">Sélectionne un véhicule dans le Garage avant d’ajouter une intervention.</p>}

      {expanded && vehicle && (
        <div className="maintenance-record-form">
          <div className="maintenance-form-grid">
            <label>Intervention *<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Ex. remplacement caméra avant" /></label>
            <label>Date *<input type="date" value={performedAt} onChange={(event) => { setPerformedAt(event.target.value); setMileageHint(""); if (mileageSource === "history_estimate") setMileageSource("manual"); }} /></label>
            <div className="maintenance-auto-field">
              <label>Kilométrage *<input type="number" min={0} step={1} value={mileageKm} onChange={(event) => { setMileageKm(event.target.value); setMileageSource("manual"); setMileageHint(""); }} placeholder={liveOdometerKm !== null ? String(Math.round(liveOdometerKm)) : "Ex. 105420"} /></label>
              <button type="button" className="ghost-button" disabled={mileageBusy || !performedAt} onClick={() => void estimateMileageForDate(performedAt)}>{mileageBusy ? "Recherche…" : performedAt === today() && liveOdometerKm !== null ? "Utiliser le CAN" : "Auto selon la date"}</button>
            </div>
            <label>Catégorie<select value={category} onChange={(event) => setCategory(event.target.value)}><option>Entretien courant</option><option>Réparation</option><option>Diagnostic</option><option>Pneumatiques</option><option>Carrosserie</option><option>Amélioration</option><option>Contrôle technique</option><option>Autre</option></select></label>
            <label>Garage / intervenant<input value={workshop} onChange={(event) => setWorkshop(event.target.value)} placeholder="Nom du garage ou réalisé soi-même" /></label>
            <label>N° de facture<input value={invoiceNumber} onChange={(event) => setInvoiceNumber(event.target.value)} /></label>
            <label>Montant TTC (€)<input type="number" min={0} step="0.01" value={invoiceTotal} onChange={(event) => setInvoiceTotal(event.target.value)} /></label>
            <label>Main-d’œuvre (h)<input type="number" min={0} step="0.1" value={laborHours} onChange={(event) => setLaborHours(event.target.value)} /></label>
          </div>

          {mileageHint && <p className={`maintenance-mileage-hint ${mileageSource === "history_estimate" ? "estimated" : "measured"}`}>{mileageHint} <strong>Valeur modifiable.</strong></p>}

          <div className="maintenance-parts-editor">
            <header><div><strong>Pièces remplacées</strong><small>Une ligne par pièce ou ensemble monté.</small></div><button type="button" className="secondary-button" onClick={() => setParts((current) => [...current, emptyPart()])}>＋ Ajouter une pièce</button></header>
            {parts.map((part, index) => (
              <div className="maintenance-part-row" key={index}>
                <label>Désignation<input value={part.name} onChange={(event) => updatePart(index, "name", event.target.value)} placeholder="Ex. caméra CVM" /></label>
                <label>Fabricant<input value={part.manufacturer} onChange={(event) => updatePart(index, "manufacturer", event.target.value)} /></label>
                <label>Référence pièce<input value={part.part_number} onChange={(event) => updatePart(index, "part_number", event.target.value)} placeholder="OEM / fournisseur" /></label>
                <label>N° de série<input value={part.serial_number} onChange={(event) => updatePart(index, "serial_number", event.target.value)} /></label>
                <label>Ancienne référence<input value={part.removed_part_number} onChange={(event) => updatePart(index, "removed_part_number", event.target.value)} placeholder="Pièce retirée" /></label>
                <label>Ancien n° de série<input value={part.removed_serial_number} onChange={(event) => updatePart(index, "removed_serial_number", event.target.value)} /></label>
                <label>Qté<input type="number" min="0.01" step="0.01" value={part.quantity} onChange={(event) => updatePart(index, "quantity", event.target.value)} /></label>
                <label>Prix unitaire (€)<input type="number" min={0} step="0.01" value={part.unit_price} onChange={(event) => updatePart(index, "unit_price", event.target.value)} /></label>
                <label>Garantie jusqu’au<input type="date" value={part.warranty_until} onChange={(event) => updatePart(index, "warranty_until", event.target.value)} /></label>
                <label>Note<input value={part.note} onChange={(event) => updatePart(index, "note", event.target.value)} /></label>
                <button type="button" className="maintenance-remove-part" disabled={parts.length === 1} onClick={() => setParts((current) => current.filter((_, partIndex) => partIndex !== index))}>Retirer</button>
              </div>
            ))}
          </div>

          <div className="maintenance-form-footer">
            <label className="maintenance-notes">Compte rendu<textarea rows={4} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Travaux réalisés, contrôles, anomalies, prochaine échéance…" /></label>
            <div className="maintenance-file-input maintenance-invoice-reader">
              <label>Factures et justificatifs<input type="file" multiple accept="application/pdf,image/jpeg,image/png,image/webp" onChange={(event) => { setDocuments(Array.from(event.target.files ?? [])); setInvoiceAnalysis(null); }} /><small>PDF ou image, 20 Mo maximum par fichier.</small></label>
              <button type="button" className="secondary-button" disabled={!documents.length || invoiceBusy} onClick={() => void analyzeSelectedInvoice()}>{invoiceBusy ? "Lecture OCR…" : "Lire et préremplir la facture"}</button>
              <small>Analyse locale. Rien n’est enregistré avant ta validation.</small>
            </div>
          </div>
          {documents.length > 0 && <p className="maintenance-selected-files">{documents.map((file) => file.name).join(" · ")}</p>}
          {invoiceAnalysis && (
            <div className="maintenance-invoice-analysis">
              <strong>Préremplissage à {Math.round(invoiceAnalysis.confidence * 100)} % · {invoiceAnalysis.ocr_used ? "OCR image" : "texte PDF"}</strong>
              {invoiceAnalysis.warnings.map((warning) => <span key={warning}>{warning}</span>)}
              <details><summary>Voir le texte détecté</summary><pre>{invoiceAnalysis.extracted_text_excerpt}</pre></details>
            </div>
          )}
          {formError && <p className="inline-alert">{formError}</p>}
          <button className="primary-button" disabled={busy} onClick={() => void handleSubmit()}>{busy ? "Enregistrement…" : "Enregistrer l’intervention"}</button>
        </div>
      )}

      {sortedRecords.length === 0 ? (
        <EmptyState title="Aucune intervention mécanique" text="Ajoute la première facture ou opération réalisée sur ce véhicule." />
      ) : (
        <div className="maintenance-record-list">
          {sortedRecords.map((record) => (
            <article className="maintenance-record-card" key={record.id}>
              <header><div><span>{new Date(`${record.performed_at}T12:00:00`).toLocaleDateString("fr-FR")}</span><h3>{record.title}</h3></div><strong>{record.mileage_source === "history_estimate" ? "≈ " : ""}{record.mileage_km.toLocaleString("fr-FR")} km</strong></header>
              <div className="maintenance-record-meta"><span>{record.category}</span>{record.mileage_source === "history_estimate" && <span>Kilométrage estimé</span>}{record.mileage_source === "can_signal" && <span>Kilométrage CAN</span>}{record.mileage_source === "invoice" && <span>Kilométrage facture</span>}{record.workshop && <span>{record.workshop}</span>}{record.invoice_number && <span>Facture {record.invoice_number}</span>}{typeof record.invoice_total === "number" && <b>{formatMoney(record.invoice_total, record.currency)}</b>}</div>
              {record.mileage_note && <p className="maintenance-record-mileage-note">{record.mileage_note}</p>}
              {record.parts.length > 0 && <div className="maintenance-record-parts">{record.parts.map((part, index) => <div key={`${part.name}-${index}`}><strong>{part.quantity} × {part.name}</strong><span>{[part.manufacturer, part.part_number && `réf. montée ${part.part_number}`, part.serial_number && `série montée ${part.serial_number}`, part.removed_part_number && `ancienne réf. ${part.removed_part_number}`, part.removed_serial_number && `ancienne série ${part.removed_serial_number}`].filter(Boolean).join(" · ") || "Référence non renseignée"}</span>{part.warranty_until && <small>Garantie jusqu’au {new Date(`${part.warranty_until}T12:00:00`).toLocaleDateString("fr-FR")}</small>}</div>)}</div>}
              {record.notes && <p>{record.notes}</p>}
              {record.documents.length > 0 && <footer>{record.documents.map((document) => <a href={`${API_BASE}${document.download_url}?vin=${encodeURIComponent(record.vin)}`} target="_blank" rel="noreferrer" key={document.id}>↗ {document.original_name}<small>{(document.size_bytes / 1024 / 1024).toFixed(1)} Mo · SHA‑256 {document.sha256.slice(0, 12)}…</small></a>)}</footer>}
              <div className="maintenance-add-document">
                <label>Ajouter une facture / photo<input type="file" multiple accept="application/pdf,image/jpeg,image/png,image/webp" onChange={(event) => setPendingDocuments((current) => ({ ...current, [record.id]: Array.from(event.target.files ?? []) }))} /></label>
                <button type="button" className="ghost-button" disabled={busy || !(pendingDocuments[record.id]?.length)} onClick={async () => { await onAddDocuments(record.id, pendingDocuments[record.id] ?? []); setPendingDocuments((current) => ({ ...current, [record.id]: [] })); }}>Joindre</button>
              </div>
              <small className="maintenance-revision">Révision {record.revision} · enregistré le {new Date(record.created_at).toLocaleDateString("fr-FR")}</small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
