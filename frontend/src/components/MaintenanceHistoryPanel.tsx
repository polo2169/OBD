import { useEffect, useMemo, useRef, useState } from "react";

import { API_BASE, api } from "../api";
import { EmptyState } from "./ui";
import type {
  DiagnosticVehicle,
  DocumentImportSnapshot,
  MaintenanceInvoiceAnalysis,
  MaintenanceForecast,
  MaintenanceForecastItem,
  MaintenanceMileageEstimate,
  MaintenancePart,
  MaintenanceRecommendation,
  MaintenanceRecord,
  MaintenanceRecordInput,
  ServiceProvider,
  ServiceProviderInput,
} from "../types";

type MaintenanceHistoryPanelProps = {
  vehicle: DiagnosticVehicle | null;
  records: MaintenanceRecord[];
  providers: ServiceProvider[];
  liveOdometerKm: number | null;
  busy: boolean;
  createIntent: { key: number; eventType: MaintenanceRecordInput["event_type"] } | null;
  onCreate: (entry: MaintenanceRecordInput, documents: File[]) => Promise<boolean>;
  onUpdate: (recordId: string, entry: MaintenanceRecordInput) => Promise<boolean>;
  onSetRecommendationStatus: (
    recordId: string,
    recommendationIndex: number,
    status: "open" | "completed" | "dismissed",
  ) => Promise<boolean>;
  onAddDocuments: (recordId: string, documents: File[]) => Promise<void>;
  onEstimateMileage: (vin: string, performedAt: string) => Promise<MaintenanceMileageEstimate | null>;
  onAnalyzeInvoice: (vin: string, document: File) => Promise<MaintenanceInvoiceAnalysis | null>;
  onCreateProvider: (entry: ServiceProviderInput) => Promise<ServiceProvider | null>;
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
  usage: MaintenancePart["usage"];
  system_code: string;
  component_code: string;
  position: NonNullable<MaintenancePart["position"]> | "";
  invoice_line_id: string;
};

type RecommendationDraft = {
  title: string;
  details: string;
  status: MaintenanceRecommendation["status"];
  source: MaintenanceRecommendation["source"];
  recommended_at_km: string;
  due_date: string;
  due_mileage_km: string;
  follow_up_after_km: string;
  confidence: MaintenanceRecommendation["confidence"];
};

const emptyRecommendation = (mileage = ""): RecommendationDraft => ({
  title: "", details: "", status: "open", source: "manual", recommended_at_km: mileage,
  due_date: "", due_mileage_km: "", follow_up_after_km: "", confidence: "high",
});

const recommendationDraft = (value: MaintenanceRecommendation): RecommendationDraft => ({
  title: value.title, details: value.details ?? "", status: value.status, source: value.source,
  recommended_at_km: value.recommended_at_km == null ? "" : String(value.recommended_at_km),
  due_date: value.due_date ?? "", due_mileage_km: value.due_mileage_km == null ? "" : String(value.due_mileage_km),
  follow_up_after_km: value.follow_up_after_km == null ? "" : String(value.follow_up_after_km), confidence: value.confidence,
});

const emptyPart = (): PartDraft => ({
  name: "", manufacturer: "", part_number: "", serial_number: "", removed_part_number: "",
  removed_serial_number: "", quantity: "1", unit_price: "", warranty_until: "", note: "",
  usage: "installed", system_code: "", component_code: "", position: "", invoice_line_id: "",
});

const partDraft = (part: MaintenancePart): PartDraft => ({
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
  usage: part.usage ?? "installed",
  system_code: part.system_code ?? "",
  component_code: part.component_code ?? "",
  position: part.position ?? "",
  invoice_line_id: part.invoice_line_id ?? "",
});

const today = () => {
  const current = new Date();
  return new Date(current.getTime() - current.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};
const optionalNumber = (value: string) => value.trim() ? Number(value) : null;
const formatMoney = (value: number, currency: string) => new Intl.NumberFormat("fr-FR", { style: "currency", currency }).format(value);
const providerLabel = (provider: ServiceProvider) => provider.display_name || provider.legal_name;
const displayDate = (value?: string | null) => value ? new Date(`${value}T12:00:00`).toLocaleDateString("fr-FR") : "À confirmer";
const forecastCost = (item: MaintenanceForecastItem) => {
  if (item.estimated_cost_min == null || item.estimated_cost_max == null) return "Coût à renseigner";
  if (item.estimated_cost_min === item.estimated_cost_max) return formatMoney(item.estimated_cost_min, "EUR");
  return `${formatMoney(item.estimated_cost_min, "EUR")} – ${formatMoney(item.estimated_cost_max, "EUR")}`;
};
const forecastDateAtMileage = (forecast: MaintenanceForecast, mileageKm: number) => {
  const current = new Date(`${forecast.current_date}T12:00:00`);
  let value: Date;
  if (mileageKm <= forecast.current_mileage_km && forecast.current_mileage_km > 0) {
    const start = new Date(`${forecast.start_date}T12:00:00`);
    value = new Date(start.getTime() + (current.getTime() - start.getTime()) * mileageKm / forecast.current_mileage_km);
  } else {
    value = new Date(current);
    value.setDate(value.getDate() + Math.round((mileageKm - forecast.current_mileage_km) / forecast.annual_mileage_km * 365.25));
  }
  return value.toLocaleDateString("fr-FR", { month: "short", year: "numeric" });
};
const FORECAST_HORIZONS = [200_000, 300_000, 500_000, 750_000, 1_000_000] as const;
const MIN_TIMELINE_ZOOM = 0.5;
const MAX_TIMELINE_ZOOM = 2;
const TIMELINE_ZOOM_STEP = 0.25;

export function MaintenanceHistoryPanel({
  vehicle, records, providers, liveOdometerKm, busy, createIntent, onCreate, onUpdate, onAddDocuments,
  onSetRecommendationStatus, onEstimateMileage, onAnalyzeInvoice, onCreateProvider,
}: MaintenanceHistoryPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [editingRecord, setEditingRecord] = useState<MaintenanceRecord | null>(null);
  const [recordStatus, setRecordStatus] = useState<MaintenanceRecordInput["record_status"]>("confirmed");
  const [eventType, setEventType] = useState<MaintenanceRecordInput["event_type"]>("maintenance");
  const [purchasedAt, setPurchasedAt] = useState("");
  const [performedAt, setPerformedAt] = useState(today);
  const [performedAtSource, setPerformedAtSource] = useState<MaintenanceRecordInput["performed_at_source"]>("manual");
  const [mileageKm, setMileageKm] = useState("");
  const [mileageSource, setMileageSource] = useState<MaintenanceRecordInput["mileage_source"]>("manual");
  const [mileageHint, setMileageHint] = useState("");
  const [mileageBusy, setMileageBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("Entretien courant");
  const [workshop, setWorkshop] = useState("");
  const [performedBy, setPerformedBy] = useState<MaintenanceRecordInput["performed_by"]>("owner");
  const [performerProviderId, setPerformerProviderId] = useState("");
  const [sellerProviderId, setSellerProviderId] = useState("");
  const [invoiceIssuerProviderId, setInvoiceIssuerProviderId] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceSubtotal, setInvoiceSubtotal] = useState("");
  const [invoiceTax, setInvoiceTax] = useState("");
  const [invoiceTotal, setInvoiceTotal] = useState("");
  const [documentClientName, setDocumentClientName] = useState("");
  const [documentVehicleVin, setDocumentVehicleVin] = useState("");
  const [documentRegistration, setDocumentRegistration] = useState("");
  const [documentPageCount, setDocumentPageCount] = useState("");
  const [documentPaginationStatus, setDocumentPaginationStatus] = useState<MaintenanceRecordInput["document_pagination_status"]>("unknown");
  const [documentDossierId, setDocumentDossierId] = useState("");
  const [laborHours, setLaborHours] = useState("");
  const [notes, setNotes] = useState("");
  const [parts, setParts] = useState<PartDraft[]>([emptyPart()]);
  const [recommendations, setRecommendations] = useState<RecommendationDraft[]>([]);
  const [documents, setDocuments] = useState<File[]>([]);
  const [importSnapshot, setImportSnapshot] = useState<DocumentImportSnapshot | null>(null);
  const [invoiceAnalysis, setInvoiceAnalysis] = useState<MaintenanceInvoiceAnalysis | null>(null);
  const [invoiceBusy, setInvoiceBusy] = useState(false);
  const [pendingDocuments, setPendingDocuments] = useState<Record<string, File[]>>({});
  const [formError, setFormError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showParts, setShowParts] = useState(false);
  const [showRecommendations, setShowRecommendations] = useState(false);
  const [historySearch, setHistorySearch] = useState("");
  const [historyFilter, setHistoryFilter] = useState<"all" | "attention" | "invoices">("all");
  const [forecast, setForecast] = useState<MaintenanceForecast | null>(null);
  const [annualMileageInput, setAnnualMileageInput] = useState("");
  const [forecastHorizonKm, setForecastHorizonKm] = useState(500_000);
  const [timelineZoom, setTimelineZoom] = useState(1);
  const [showAllForecastItems, setShowAllForecastItems] = useState(false);
  const timelineScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!vehicle) { setForecast(null); return; }
    setAnnualMileageInput(window.localStorage.getItem(`maintenance-annual-km:${vehicle.vin}`) ?? "");
    const savedHorizon = Number(window.localStorage.getItem(`maintenance-forecast-horizon:${vehicle.vin}`));
    setForecastHorizonKm(FORECAST_HORIZONS.includes(savedHorizon as typeof FORECAST_HORIZONS[number]) ? savedHorizon : 500_000);
    const savedZoom = Number(window.localStorage.getItem(`maintenance-timeline-zoom:${vehicle.vin}`));
    setTimelineZoom(savedZoom >= MIN_TIMELINE_ZOOM && savedZoom <= MAX_TIMELINE_ZOOM ? savedZoom : 1);
    setShowAllForecastItems(false);
  }, [vehicle?.vin]);

  useEffect(() => {
    if (!vehicle) return;
    const annualMileage = Number(annualMileageInput);
    if (annualMileageInput && (!Number.isInteger(annualMileage) || annualMileage < 1_000 || annualMileage > 100_000)) return;
    const timer = window.setTimeout(() => {
      const query = new URLSearchParams({ vin: vehicle.vin, horizon_mileage_km: String(forecastHorizonKm) });
      if (annualMileageInput) query.set("annual_mileage_km", annualMileageInput);
      void api<MaintenanceForecast>(`/api/maintenance/forecast?${query.toString()}`)
        .then(setForecast)
        .catch(() => setForecast(null));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [annualMileageInput, forecastHorizonKm, records, vehicle?.vin]);

  function updateAnnualMileage(value: string) {
    const normalized = value.replace(/\D/g, "").slice(0, 6);
    setAnnualMileageInput(normalized);
    if (!vehicle) return;
    if (normalized) window.localStorage.setItem(`maintenance-annual-km:${vehicle.vin}`, normalized);
    else window.localStorage.removeItem(`maintenance-annual-km:${vehicle.vin}`);
  }

  function updateForecastHorizon(value: number) {
    if (!FORECAST_HORIZONS.includes(value as typeof FORECAST_HORIZONS[number])) return;
    setForecastHorizonKm(value);
    setShowAllForecastItems(false);
    if (vehicle) window.localStorage.setItem(`maintenance-forecast-horizon:${vehicle.vin}`, String(value));
  }

  function updateTimelineZoom(value: number) {
    const normalized = Math.min(MAX_TIMELINE_ZOOM, Math.max(MIN_TIMELINE_ZOOM, Math.round(value / TIMELINE_ZOOM_STEP) * TIMELINE_ZOOM_STEP));
    setTimelineZoom(normalized);
    if (vehicle) window.localStorage.setItem(`maintenance-timeline-zoom:${vehicle.vin}`, String(normalized));
  }

  const sortedRecords = useMemo(() => [...records].sort((left, right) => {
    const leftDate = left.performed_at || left.purchased_at || "";
    const rightDate = right.performed_at || right.purchased_at || "";
    return rightDate.localeCompare(leftDate) || right.updated_at.localeCompare(left.updated_at);
  }), [records]);
  const visibleRecords = useMemo(() => {
    const query = historySearch.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("fr").trim();
    return sortedRecords.filter((record) => {
      const hasOpenRecommendation = record.recommendations.some((recommendation) => recommendation.status === "open" || recommendation.status === "monitoring");
      if (historyFilter === "attention" && record.record_status !== "draft" && !hasOpenRecommendation) return false;
      if (historyFilter === "invoices" && !record.invoice_number && !record.documents.some((document) => document.kind === "invoice")) return false;
      if (!query) return true;
      const haystack = [record.title, record.category, record.workshop, record.invoice_number, record.document_client_name,
        ...record.parts.flatMap((part) => [part.name, part.manufacturer, part.part_number]),
        ...record.recommendations.map((recommendation) => recommendation.title),
      ].filter(Boolean).join(" ").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("fr");
      return haystack.includes(query);
    });
  }, [historyFilter, historySearch, sortedRecords]);
  const providersById = useMemo(() => new Map(providers.map((provider) => [provider.id, provider])), [providers]);
  const totalSpent = records.reduce((sum, record) => sum + (record.invoice_total ?? 0), 0);
  const partCount = records.reduce((sum, record) => sum + record.parts.filter((part) => part.usage === "installed" || part.usage === "consumed").length, 0);
  const currentMileage = liveOdometerKm ?? Math.max(0, ...records.map((record) => record.mileage_km ?? 0));
  const dueRecommendations = records.flatMap((record) => record.recommendations.map((recommendation) => {
    const dueMileage = recommendation.due_mileage_km ?? (
      recommendation.recommended_at_km != null && recommendation.follow_up_after_km != null
        ? recommendation.recommended_at_km + recommendation.follow_up_after_km : null
    );
    const due = recommendation.status === "open" && (
      (dueMileage != null && currentMileage >= dueMileage)
      || (recommendation.due_date != null && recommendation.due_date <= today())
    );
    return { record, recommendation, dueMileage, due };
  })).filter((item) => item.due);
  const openRecommendations = records.flatMap((record) => record.recommendations
    .filter((recommendation) => recommendation.status === "open" || recommendation.status === "monitoring")
    .map((recommendation) => ({ record, recommendation })));
  const predictiveItems = forecast?.items.filter((item) => item.kind !== "history") ?? [];
  const visiblePredictiveItems = showAllForecastItems ? predictiveItems : predictiveItems.slice(0, 12);
  const nextTwoYears = forecast ? new Date(`${forecast.current_date}T12:00:00`) : null;
  if (nextTwoYears) nextTwoYears.setFullYear(nextTwoYears.getFullYear() + 2);
  const nearTermItems = forecast?.items.filter((item) => (
    item.kind !== "history" && nextTwoYears && new Date(`${item.due_date}T12:00:00`) <= nextTwoYears
  )) ?? [];
  const nearTermCost = nearTermItems.reduce((total, item) => ({
    min: total.min + (item.estimated_cost_min ?? 0),
    max: total.max + (item.estimated_cost_max ?? 0),
  }), { min: 0, max: 0 });
  const timelineTickStep = forecast && forecast.horizon_mileage_km <= 200_000
    ? 20_000 : forecast && forecast.horizon_mileage_km <= 300_000 ? 30_000
      : forecast && forecast.horizon_mileage_km <= 500_000 ? 50_000 : forecast && forecast.horizon_mileage_km <= 750_000 ? 75_000 : 100_000;
  const timelineTicks = forecast
    ? Array.from({ length: Math.floor(forecast.horizon_mileage_km / timelineTickStep) + 1 }, (_, index) => index * timelineTickStep)
    : [];
  const timelineCanvasWidth = forecast
    ? Math.max(900, Math.round(3_600 * forecast.horizon_mileage_km / 500_000 * timelineZoom))
    : 3_600;

  function centerTimelineOnCurrentMileage() {
    if (!forecast || !timelineScrollRef.current) return;
    const container = timelineScrollRef.current;
    const currentPosition = forecast.current_mileage_km / forecast.horizon_mileage_km * timelineCanvasWidth;
    container.scrollTo({ left: Math.max(0, currentPosition - container.clientWidth / 2), behavior: "smooth" });
  }

  function resetForm() {
    setEditingRecord(null); setRecordStatus("confirmed"); setEventType("maintenance"); setPurchasedAt("");
    setPerformedAt(today()); setPerformedAtSource("manual"); setMileageKm(""); setMileageSource("manual");
    setMileageHint(""); setTitle(""); setCategory("Entretien courant"); setWorkshop(""); setPerformedBy("owner");
    setPerformerProviderId(""); setSellerProviderId(""); setInvoiceIssuerProviderId(""); setInvoiceNumber("");
    setInvoiceSubtotal(""); setInvoiceTax(""); setInvoiceTotal(""); setDocumentClientName(""); setDocumentVehicleVin("");
    setDocumentRegistration(""); setDocumentPageCount(""); setDocumentPaginationStatus("unknown"); setDocumentDossierId(""); setLaborHours(""); setNotes("");
    setParts([emptyPart()]); setRecommendations([]); setDocuments([]); setImportSnapshot(null); setInvoiceAnalysis(null); setFormError(""); setExpanded(false);
    setShowAdvanced(false); setShowParts(false); setShowRecommendations(false);
  }

  useEffect(() => {
    if (!createIntent || !vehicle) return;
    resetForm();
    setEventType(createIntent.eventType);
    setCategory(createIntent.eventType === "repair" ? "Réparation" : "Entretien courant");
    setExpanded(true);
    window.setTimeout(() => document.querySelector(".maintenance-record-form")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }, [createIntent?.key, vehicle?.vin]);

  function startEdit(record: MaintenanceRecord) {
    setEditingRecord(record); setRecordStatus(record.record_status ?? "confirmed"); setEventType(record.event_type ?? "maintenance");
    setPurchasedAt(record.purchased_at ?? ""); setPerformedAt(record.performed_at ?? "");
    setPerformedAtSource(record.performed_at_source ?? "manual"); setMileageKm(record.mileage_km == null ? "" : String(record.mileage_km));
    setMileageSource(record.mileage_source); setMileageHint(record.mileage_note ?? ""); setTitle(record.title); setCategory(record.category);
    setWorkshop(record.workshop ?? ""); setPerformedBy(record.performed_by ?? "unknown"); setPerformerProviderId(record.performer_provider_id ?? "");
    setSellerProviderId(record.seller_provider_id ?? ""); setInvoiceIssuerProviderId(record.invoice_issuer_provider_id ?? "");
    setInvoiceNumber(record.invoice_number ?? ""); setInvoiceSubtotal(record.invoice_subtotal == null ? "" : String(record.invoice_subtotal));
    setInvoiceTax(record.invoice_tax == null ? "" : String(record.invoice_tax)); setInvoiceTotal(record.invoice_total == null ? "" : String(record.invoice_total));
    setDocumentClientName(record.document_client_name ?? ""); setDocumentVehicleVin(record.document_vehicle_vin ?? "");
    setDocumentRegistration(record.document_registration ?? ""); setDocumentPageCount(record.document_page_count == null ? "" : String(record.document_page_count));
    setDocumentPaginationStatus(record.document_pagination_status ?? "unknown"); setDocumentDossierId(record.document_dossier_id ?? "");
    setLaborHours(record.labor_hours == null ? "" : String(record.labor_hours)); setNotes(record.notes ?? "");
    setParts(record.parts.length ? record.parts.map(partDraft) : [emptyPart()]); setRecommendations(record.recommendations.map(recommendationDraft)); setDocuments([]); setImportSnapshot(record.import_snapshot ?? null);
    setInvoiceAnalysis(null); setFormError(""); setExpanded(true);
    setShowAdvanced(false); setShowParts(false); setShowRecommendations(false);
    window.setTimeout(() => document.querySelector(".maintenance-record-form")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  function updatePart(index: number, key: keyof PartDraft, value: string) {
    setParts((current) => current.map((part, partIndex) => partIndex === index ? { ...part, [key]: value } : part));
  }

  function updateRecommendation(index: number, key: keyof RecommendationDraft, value: string) {
    setRecommendations((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: value } : item));
  }

  function applyProvider(providerId: string, kind?: ServiceProviderInput["kind"]) {
    if (!providerId) return;
    setInvoiceIssuerProviderId(providerId);
    if (kind === "parts_supplier") {
      setSellerProviderId(providerId); setPerformedBy("owner"); setPerformerProviderId("");
    } else {
      setPerformedBy("service_provider"); setPerformerProviderId(providerId);
    }
    const provider = providersById.get(providerId);
    if (provider) setWorkshop(providerLabel(provider));
  }

  async function estimateMileageForDate(dateValue: string) {
    if (!vehicle || !dateValue) return;
    if (dateValue === today() && liveOdometerKm !== null) {
      const mileage = Math.round(liveOdometerKm); setMileageKm(String(mileage)); setMileageSource("can_signal");
      setMileageHint(`Lecture CAN actuelle : ${mileage.toLocaleString("fr-FR")} km.`); return;
    }
    setMileageBusy(true);
    try {
      const estimate = await onEstimateMileage(vehicle.vin, dateValue);
      if (!estimate) return;
      setMileageHint(estimate.message);
      if (typeof estimate.mileage_km === "number") { setMileageKm(String(estimate.mileage_km)); setMileageSource("history_estimate"); }
    } finally { setMileageBusy(false); }
  }

  async function analyzeSelectedInvoice() {
    if (!vehicle || !documents.length) return;
    setInvoiceBusy(true); setFormError("");
    try {
      const analysis = await onAnalyzeInvoice(vehicle.vin, documents[0]);
      if (!analysis) return;
      setInvoiceAnalysis(analysis); setImportSnapshot(analysis.import_snapshot); setPurchasedAt(analysis.purchased_at ?? "");
      setPerformedAt(analysis.performed_at ?? ""); setPerformedAtSource(analysis.performed_at_source ?? "manual");
      setRecordStatus(analysis.performed_at ? "confirmed" : "draft");
      if (analysis.title) setTitle(analysis.title); if (analysis.category) setCategory(analysis.category);
      if (analysis.workshop) setWorkshop(analysis.workshop); if (analysis.invoice_number) setInvoiceNumber(analysis.invoice_number);
      if (typeof analysis.invoice_total === "number") setInvoiceTotal(String(analysis.invoice_total));
      if (analysis.parts.length) setParts(analysis.parts.map(partDraft));
      if (analysis.parts.length) setShowParts(true);
      if (analysis.matched_provider_id) applyProvider(analysis.matched_provider_id, analysis.provider_candidate?.kind);
      else if (analysis.provider_candidate?.kind === "parts_supplier") setPerformedBy("owner");
      else if (analysis.provider_candidate) setPerformedBy("unknown");
      if (typeof analysis.mileage_km === "number") {
        setMileageKm(String(analysis.mileage_km)); setMileageSource("invoice");
        setMileageHint(`Kilométrage lu sur la facture : ${analysis.mileage_km.toLocaleString("fr-FR")} km.`);
      } else if (analysis.performed_at) await estimateMileageForDate(analysis.performed_at);
    } finally { setInvoiceBusy(false); }
  }

  async function createDetectedProvider() {
    const candidate = invoiceAnalysis?.provider_candidate;
    if (!candidate) return;
    const saved = await onCreateProvider({ ...candidate, verified_by_user: true });
    if (saved) applyProvider(saved.id, saved.kind);
  }

  async function handleSubmit() {
    if (!vehicle) return;
    if (!title.trim()) { setFormError("Indique le nom de l’intervention."); return; }
    if (recordStatus === "confirmed" && !performedAt) { setFormError("Une intervention confirmée doit avoir une date de pose/réalisation."); return; }
    const mileage = mileageKm.trim() ? Number(mileageKm) : null;
    if (mileage !== null && (!Number.isInteger(mileage) || mileage < 0)) { setFormError("Le kilométrage doit être un nombre entier positif."); return; }
    if (performedBy === "service_provider" && !performerProviderId) { setFormError("Sélectionne le professionnel qui a réalisé l’intervention."); return; }
    const normalizedParts: MaintenancePart[] = [];
    for (const part of parts) {
      if (!part.name.trim()) continue;
      const quantity = Number(part.quantity); const unitPrice = optionalNumber(part.unit_price);
      if (!Number.isFinite(quantity) || quantity <= 0 || (unitPrice !== null && !Number.isFinite(unitPrice))) { setFormError("Vérifie la quantité et le prix des pièces."); return; }
      normalizedParts.push({
        name: part.name.trim(), manufacturer: part.manufacturer.trim() || null, part_number: part.part_number.trim() || null,
        serial_number: part.serial_number.trim() || null, removed_part_number: part.removed_part_number.trim() || null,
        removed_serial_number: part.removed_serial_number.trim() || null, quantity, unit_price: unitPrice,
        warranty_until: part.warranty_until || null, note: part.note.trim() || null, usage: part.usage,
        system_code: part.system_code.trim() || null, component_code: part.component_code.trim() || null,
        position: part.position || null, invoice_line_id: part.invoice_line_id.trim() || null,
      });
    }
    const subtotal = optionalNumber(invoiceSubtotal); const tax = optionalNumber(invoiceTax); const total = optionalNumber(invoiceTotal); const labor = optionalNumber(laborHours);
    if ([subtotal, tax, total, labor].some((value) => value !== null && (!Number.isFinite(value) || value < 0))) { setFormError("Vérifie les montants et le temps de main-d’œuvre."); return; }
    const pageCount = optionalNumber(documentPageCount);
    const normalizedDocumentVin = documentVehicleVin.trim().toUpperCase();
    if (pageCount !== null && (!Number.isInteger(pageCount) || pageCount <= 0)) { setFormError("Le nombre de pages doit être un entier positif."); return; }
    if (normalizedDocumentVin && !/^[A-HJ-NPR-Z0-9]{17}$/.test(normalizedDocumentVin)) { setFormError("Le VIN lu sur le document doit contenir 17 caractères valides."); return; }
    const performer = performerProviderId ? providersById.get(performerProviderId) : null;
    const normalizedRecommendations: MaintenanceRecommendation[] = [];
    for (const [recommendationIndex, recommendation] of recommendations.entries()) {
      if (!recommendation.title.trim()) continue;
      const recommendedAt = optionalNumber(recommendation.recommended_at_km);
      const dueMileage = optionalNumber(recommendation.due_mileage_km);
      const followUp = optionalNumber(recommendation.follow_up_after_km);
      if ([recommendedAt, dueMileage].some((value) => value !== null && (!Number.isInteger(value) || value < 0)) || (followUp !== null && (!Number.isInteger(followUp) || followUp <= 0))) {
        setFormError("Vérifie les kilométrages des recommandations."); return;
      }
      const sourceRecommendation = editingRecord?.recommendations[recommendationIndex];
      const preserveAutomaticCompletion = recommendation.status === "completed" && sourceRecommendation?.auto_managed;
      normalizedRecommendations.push({
        title: recommendation.title.trim(), details: recommendation.details.trim() || null,
        status: recommendation.status, source: recommendation.source,
        recommended_at_km: recommendedAt, due_date: recommendation.due_date || null,
        due_mileage_km: dueMileage, follow_up_after_km: followUp, confidence: recommendation.confidence,
        auto_managed: Boolean(preserveAutomaticCompletion),
        completed_by_record_id: preserveAutomaticCompletion ? sourceRecommendation.completed_by_record_id ?? null : null,
        completed_at: preserveAutomaticCompletion ? sourceRecommendation.completed_at ?? null : null,
        completion_reason: preserveAutomaticCompletion ? sourceRecommendation.completion_reason ?? null : null,
      });
    }
    const entry: MaintenanceRecordInput = {
      vin: vehicle.vin, vehicle_profile: vehicle.vehicle_profile, schema_version: 1, record_status: recordStatus,
      source_system: editingRecord?.source_system ?? null, source_import_key: editingRecord?.source_import_key ?? null,
      event_type: eventType, purchased_at: purchasedAt || null, performed_at: performedAt || null,
      performed_at_source: performedAt ? performedAtSource : "manual", mileage_km: mileage, mileage_source: mileageSource,
      mileage_note: mileageSource === "manual" ? null : mileageHint || null, title: title.trim(), category,
      workshop: performer ? providerLabel(performer) : workshop.trim() || null, performed_by: performedBy,
      performer_provider_id: performedBy === "service_provider" ? performerProviderId || null : null,
      seller_provider_id: sellerProviderId || null, invoice_issuer_provider_id: invoiceIssuerProviderId || null,
      invoice_number: invoiceNumber.trim() || null,
      document_client_name: documentClientName.trim() || null,
      document_vehicle_vin: normalizedDocumentVin || null,
      document_registration: documentRegistration.trim().toUpperCase() || null,
      document_page_count: pageCount,
      document_pagination_status: documentPaginationStatus,
      document_dossier_id: documentDossierId.trim() || null,
      invoice_subtotal: subtotal, invoice_tax: tax, invoice_total: total,
      currency: "EUR", labor_hours: labor, notes: notes.trim() || null, parts: normalizedParts,
      cost_lines: editingRecord?.cost_lines ?? [], recommendations: normalizedRecommendations, import_snapshot: importSnapshot,
    };
    const saved = editingRecord ? await onUpdate(editingRecord.id, entry) : await onCreate(entry, documents);
    if (saved) resetForm();
  }

  const providerOptions = <><option value="">— Aucun —</option>{providers.map((provider) => <option value={provider.id} key={provider.id}>{providerLabel(provider)} · {provider.kind.replaceAll("_", " ")}</option>)}</>;
  const localPreviewUrl = useMemo(() => documents[0] ? URL.createObjectURL(documents[0]) : "", [documents]);
  useEffect(() => () => { if (localPreviewUrl) URL.revokeObjectURL(localPreviewUrl); }, [localPreviewUrl]);
  const previewDocument = editingRecord?.documents[0] ?? null;
  const previewUrl = previewDocument
    ? `${API_BASE}${previewDocument.download_url}?vin=${encodeURIComponent(editingRecord?.vin ?? "")}&v=${previewDocument.sha256.slice(0, 12)}`
    : localPreviewUrl;
  const previewMediaType = previewDocument?.media_type ?? documents[0]?.type ?? "";

  return (
    <section className="panel maintenance-history-panel">
      <div className="section-heading"><div><span className="eyebrow">Dossier mécanique par VIN</span><h2>Historique des interventions</h2><p>Factures, pièces, diagnostics et preuves restent corrigeables tout en conservant le texte importé.</p></div><button className="primary-button" disabled={!vehicle} onClick={() => expanded ? resetForm() : setExpanded(true)}>{expanded ? "Fermer le formulaire" : "＋ Ajouter une intervention"}</button></div>
      <div className="maintenance-history-metrics"><article><span>Interventions</span><strong>{records.length}</strong></article><article><span>Pièces montées</span><strong>{partCount}</strong></article><article><span>Factures jointes</span><strong>{records.reduce((sum, record) => sum + record.documents.length, 0)}</strong></article><article><span>Total documenté</span><strong>{formatMoney(totalSpent, "EUR")}</strong></article></div>
      {forecast && <section className="maintenance-forecast-panel">
        <header className="maintenance-forecast-heading">
          <div className="maintenance-forecast-title"><span className="eyebrow">Maintenance prédictive</span><h3>Du début de vie jusqu’à {forecast.horizon_mileage_km.toLocaleString("fr-FR")} km</h3><p>L’historique confirmé est prolongé avec les recommandations ouvertes et les périodicités des pièces déjà remplacées.</p></div>
          <div className="maintenance-forecast-controls">
            <label>Kilométrage annuel<input type="number" min={1000} max={100000} step={500} value={annualMileageInput} onChange={(event) => updateAnnualMileage(event.target.value)} placeholder={String(forecast.annual_mileage_km)} /><small>{annualMileageInput ? "Réglage personnel" : forecast.annual_mileage_source}</small></label>
            <label>Horizon de la frise<select value={forecastHorizonKm} onChange={(event) => updateForecastHorizon(Number(event.target.value))}>{FORECAST_HORIZONS.map((horizon) => <option value={horizon} disabled={horizon <= forecast.current_mileage_km} key={horizon}>{horizon.toLocaleString("fr-FR")} km</option>)}</select><small>Distance maximale affichée</small></label>
            <div className="maintenance-timeline-scale-control"><span>Échelle · {Math.round(timelineZoom * 100)} %</span><div><button type="button" aria-label="Réduire l’échelle de la frise" disabled={timelineZoom <= MIN_TIMELINE_ZOOM} onClick={() => updateTimelineZoom(timelineZoom - TIMELINE_ZOOM_STEP)}>−</button><input type="range" aria-label="Échelle de la frise" min={MIN_TIMELINE_ZOOM} max={MAX_TIMELINE_ZOOM} step={TIMELINE_ZOOM_STEP} value={timelineZoom} onChange={(event) => updateTimelineZoom(Number(event.target.value))} /><button type="button" aria-label="Agrandir l’échelle de la frise" disabled={timelineZoom >= MAX_TIMELINE_ZOOM} onClick={() => updateTimelineZoom(timelineZoom + TIMELINE_ZOOM_STEP)}>＋</button></div><small>Plus compact ou plus détaillé</small></div>
            <button type="button" className="maintenance-timeline-today-button" onClick={centerTimelineOnCurrentMileage}>◎ Recentrer sur aujourd’hui</button>
          </div>
        </header>
        <div className="maintenance-forecast-metrics">
          <article><span>Aujourd’hui</span><strong>{forecast.current_mileage_km.toLocaleString("fr-FR")} km</strong><small>{displayDate(forecast.current_date)}</small></article>
          <article><span>Rythme retenu</span><strong>{forecast.annual_mileage_km.toLocaleString("fr-FR")} km/an</strong><small>Modifiable ci-dessus</small></article>
          <article><span>À traiter maintenant</span><strong>{predictiveItems.filter((item) => item.status === "due").length}</strong><small>recommandation(s) ou échéance(s)</small></article>
          <article><span>Budget indicatif · 2 ans</span><strong>{formatMoney(nearTermCost.min, "EUR")} – {formatMoney(nearTermCost.max, "EUR")}</strong><small>Pièces + pose · fourchettes indicatives</small></article>
        </div>
        <div className="maintenance-forecast-legend"><span className="history">Historique</span><span className="due">À faire maintenant</span><span className="scheduled">Prévision</span><small>Les dates futures sont calculées avec {forecast.annual_mileage_km.toLocaleString("fr-FR")} km/an.</small></div>
        <div className="maintenance-timeline-scroll" ref={timelineScrollRef} aria-label={`Frise de maintenance de zéro à ${forecast.horizon_mileage_km.toLocaleString("fr-FR")} kilomètres`}>
          <div className="maintenance-timeline-canvas" style={{ width: timelineCanvasWidth }}>
            <div className="maintenance-timeline-axis" />
            {timelineTicks.map((mileage) => <div className="maintenance-timeline-tick" style={{ left: `${mileage / forecast.horizon_mileage_km * 100}%` }} key={mileage}><b>{mileage === 0 ? "0" : `${mileage / 1000}k`}</b><small>{forecastDateAtMileage(forecast, mileage)}</small></div>)}
            <div className="maintenance-timeline-now" style={{ left: `${forecast.current_mileage_km / forecast.horizon_mileage_km * 100}%` }}><strong>Aujourd’hui</strong><small>{forecast.current_mileage_km.toLocaleString("fr-FR")} km</small></div>
            {forecast.items.map((item, index) => {
              const labelled = item.kind === "recommendation" || item.kind === "scheduled" && item.sequence === 1 || item.kind === "history" && index % 3 === 0;
              const top = item.kind === "history" ? 218 + index % 3 * 31 : item.kind === "recommendation" ? 16 + index % 5 * 30 : labelled ? 88 + index % 4 * 24 : 176;
              return <div className={`maintenance-timeline-marker ${item.kind} ${item.status} ${labelled ? "labelled" : "compact"}`} style={{ left: `${Math.min(100, Math.max(0, item.mileage_km / forecast.horizon_mileage_km * 100))}%`, top }} title={`${item.title} · ${item.mileage_km.toLocaleString("fr-FR")} km · ${displayDate(item.due_date)} · ${forecastCost(item)}`} key={item.id}><i />{labelled && <span><strong>{item.title}</strong><small>{item.mileage_km.toLocaleString("fr-FR")} km · {displayDate(item.due_date)}</small></span>}</div>;
            })}
          </div>
        </div>
        <div className="maintenance-forecast-list">
          {visiblePredictiveItems.map((item) => <article className={item.status} key={`card-${item.id}`}>
            <div><span>{item.status === "due" ? "À faire maintenant" : item.kind === "recommendation" ? "Recommandation" : "Prévision périodique"}</span><h4>{item.title}</h4><small>{item.source_label}</small></div>
            <dl><div><dt>Kilométrage</dt><dd>{item.mileage_km.toLocaleString("fr-FR")} km</dd></div><div><dt>Date estimée</dt><dd>{displayDate(item.due_date)}</dd></div><div><dt>Coût prévu</dt><dd>{forecastCost(item)}</dd></div></dl>
            {item.kind === "recommendation" && item.record_id && item.recommendation_index != null && <div className="maintenance-recommendation-actions"><button type="button" disabled={busy} onClick={() => void onSetRecommendationStatus(item.record_id!, item.recommendation_index!, "completed")}>✓ Marquer réalisée</button><button type="button" disabled={busy} onClick={() => void onSetRecommendationStatus(item.record_id!, item.recommendation_index!, "dismissed")}>Classer sans suite</button></div>}
          </article>)}
        </div>
        {predictiveItems.length > 12 && <button type="button" className="ghost-button maintenance-forecast-more" onClick={() => setShowAllForecastItems((value) => !value)}>{showAllForecastItems ? "Afficher seulement les 12 prochaines" : `Voir les ${predictiveItems.length} échéances jusqu’à ${forecast.horizon_mileage_km.toLocaleString("fr-FR")} km`}</button>}
      </section>}
      {openRecommendations.length > 0 && <div className="maintenance-reminder-alert"><strong>{openRecommendations.length} recommandation(s) ouverte(s) · {dueRecommendations.length} échéance(s) atteinte(s)</strong>{dueRecommendations.map(({ record, recommendation, dueMileage }, index) => <span key={`${record.id}-${recommendation.title}-${index}`}>⚠ {recommendation.title}{dueMileage ? ` · seuil ${dueMileage.toLocaleString("fr-FR")} km` : recommendation.due_date ? ` · prévu le ${displayDate(recommendation.due_date)}` : ""} · source « {record.title} »</span>)}<details><summary>Voir toutes les recommandations ouvertes</summary>{openRecommendations.map(({ record, recommendation }, index) => <span key={`${record.id}-open-${index}`}>{recommendation.title} · source « {record.title} »</span>)}</details></div>}
      {!vehicle && <p className="inline-alert">Sélectionne un véhicule dans le Garage avant d’ajouter une intervention.</p>}

      {expanded && vehicle && (
        <div className={`maintenance-record-form ${previewUrl ? "with-document" : ""}`}>
          <header className="maintenance-form-title"><div><span>{editingRecord ? "Correction" : eventType === "repair" ? "Nouvelle réparation" : "Nouvelle intervention"}</span><h3>{editingRecord ? editingRecord.title : eventType === "repair" ? "Ajouter une réparation" : "Ajouter un entretien"}</h3></div><button type="button" className="ghost-button" onClick={resetForm}>Annuler</button></header>

          <div className="maintenance-validation-layout">
          <div className="maintenance-validation-data">

          <section className="maintenance-simple-step">
            <div className="maintenance-step-heading"><b>1</b><div><strong>Justificatif</strong><small>Facultatif — une photo ou un PDF peut remplir le formulaire pour toi.</small></div></div>
            {!editingRecord ? <div className="maintenance-document-start"><label className="maintenance-upload-card"><span>{documents.length ? `${documents.length} fichier(s) sélectionné(s)` : "Choisir une facture, un rapport ou une photo"}</span><small>PDF, JPEG, PNG ou WebP · 20 Mo maximum</small><input type="file" multiple accept="application/pdf,image/jpeg,image/png,image/webp" onChange={(event) => { setDocuments(Array.from(event.target.files ?? [])); setInvoiceAnalysis(null); }} /></label><button type="button" className="secondary-button" disabled={!documents.length || invoiceBusy} onClick={() => void analyzeSelectedInvoice()}>{invoiceBusy ? "Lecture en cours…" : "Lire le premier document"}</button></div> : <p className="maintenance-edit-proof">Les justificatifs déjà enregistrés sont conservés. Tu peux en joindre d’autres directement depuis la fiche après sauvegarde.</p>}
            {documents.length > 0 && <p className="maintenance-selected-files">{documents.map((file) => file.name).join(" · ")}</p>}
            {invoiceAnalysis && <div className="maintenance-invoice-analysis"><strong>{Math.round(invoiceAnalysis.confidence * 100)} % de confiance · {invoiceAnalysis.ocr_used ? "OCR local" : "texte PDF"}</strong>{invoiceAnalysis.provider_candidate && !invoiceAnalysis.matched_provider_id && <button type="button" className="secondary-button" onClick={() => void createDetectedProvider()}>Ajouter « {invoiceAnalysis.provider_candidate.legal_name} » à l’annuaire</button>}{invoiceAnalysis.warnings.map((warning) => <span key={warning}>{warning}</span>)}<details><summary>Voir le texte détecté</summary><pre>{invoiceAnalysis.extracted_text_excerpt}</pre></details></div>}
          </section>

          <section className="maintenance-simple-step">
            <div className="maintenance-step-heading"><b>2</b><div><strong>L’essentiel</strong><small>Ces informations suffisent pour enregistrer l’intervention.</small></div></div>
            <div className="maintenance-essential-grid">
              <label>Objet de l’intervention *<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Ex. Remplacement des disques et plaquettes avant" /></label>
              <label>Type d’intervention<select value={eventType} onChange={(event) => setEventType(event.target.value as MaintenanceRecordInput["event_type"])}><option value="maintenance">Entretien</option><option value="repair">Réparation</option><option value="diagnostic">Diagnostic</option><option value="inspection">Contrôle</option><option value="technical_inspection">Contrôle technique</option><option value="upgrade">Modification</option><option value="other">Autre</option></select></label>
              <label>Date de l’intervention<input type="date" value={performedAt} onChange={(event) => { const value = event.target.value; setPerformedAt(value); setPerformedAtSource("manual"); setRecordStatus(value ? "confirmed" : "draft"); }} /></label>
              <div className="maintenance-auto-field"><label>Kilométrage<input type="number" min={0} step={1} value={mileageKm} onChange={(event) => { setMileageKm(event.target.value); setMileageSource("manual"); setMileageHint(""); }} placeholder="Ex. 105420" /></label><button type="button" className="ghost-button" disabled={mileageBusy || !performedAt} onClick={() => void estimateMileageForDate(performedAt)}>{mileageBusy ? "Recherche…" : "Estimer"}</button></div>
              <label>Réalisé par<select value={performedBy} onChange={(event) => { const value = event.target.value as MaintenanceRecordInput["performed_by"]; setPerformedBy(value); if (value !== "service_provider") setPerformerProviderId(""); }}><option value="owner">Moi-même</option><option value="service_provider">Un professionnel</option><option value="unknown">Je ne sais pas</option></select></label>
              {performedBy === "service_provider" && <label>Garage<select value={performerProviderId} onChange={(event) => applyProvider(event.target.value)}>{providerOptions}</select><small>Le garage n’apparaît pas ? Ajoute-le dans l’annuaire au-dessus.</small></label>}
            </div>
          </section>
          {mileageHint && <p className={`maintenance-mileage-hint ${mileageSource === "history_estimate" ? "estimated" : "measured"}`}>{mileageHint} <strong>Valeur modifiable.</strong></p>}
          {!performedAt && <p className="inline-alert">La date d’achat est conservée, mais l’intervention restera à confirmer jusqu’à ce que tu renseignes la date de pose.</p>}

          <button type="button" className="maintenance-disclosure" onClick={() => setShowAdvanced((value) => !value)}><span><strong>Informations de facture et du document</strong><small>N° de facture, achat, montants, client, VIN et pagination</small></span><b>{showAdvanced ? "Masquer" : "Afficher"}</b></button>
          {showAdvanced && <section className="maintenance-advanced-panel">
            <div className="maintenance-form-grid">
              <label>Statut<select value={recordStatus} onChange={(event) => setRecordStatus(event.target.value as MaintenanceRecordInput["record_status"])}><option value="confirmed">Intervention confirmée</option><option value="draft">À confirmer</option></select></label>
              <label>Catégorie<input value={category} onChange={(event) => setCategory(event.target.value)} /></label>
              <label>Date d’achat / facture<input type="date" value={purchasedAt} onChange={(event) => setPurchasedAt(event.target.value)} /></label>
              <label>Origine de la date d’intervention<select value={performedAtSource} disabled={!performedAt} onChange={(event) => setPerformedAtSource(event.target.value as MaintenanceRecordInput["performed_at_source"])}><option value="manual">Saisie utilisateur</option><option value="document_explicit">Écrite sur le document</option><option value="vehicle_return">Restitution du véhicule</option><option value="invoice_date_assumed">Date de facture garage</option><option value="estimated">Estimée</option></select></label>
              <label>Vendeur de pièces<select value={sellerProviderId} onChange={(event) => setSellerProviderId(event.target.value)}>{providerOptions}</select></label>
              <label>Émetteur de facture<select value={invoiceIssuerProviderId} onChange={(event) => setInvoiceIssuerProviderId(event.target.value)}>{providerOptions}</select></label>
              <label>Intervenant lu sur le document<input value={workshop} onChange={(event) => setWorkshop(event.target.value)} /></label>
              <label>N° de facture<input value={invoiceNumber} onChange={(event) => setInvoiceNumber(event.target.value)} /></label>
              <label>Total HT (€)<input type="number" min={0} step="0.01" value={invoiceSubtotal} onChange={(event) => setInvoiceSubtotal(event.target.value)} /></label>
              <label>TVA (€)<input type="number" min={0} step="0.01" value={invoiceTax} onChange={(event) => setInvoiceTax(event.target.value)} /></label>
              <label>Total TTC (€)<input type="number" min={0} step="0.01" value={invoiceTotal} onChange={(event) => setInvoiceTotal(event.target.value)} /></label>
              <label>Main-d’œuvre (h)<input type="number" min={0} step="0.1" value={laborHours} onChange={(event) => setLaborHours(event.target.value)} /></label>
              <label>Client lu<input value={documentClientName} onChange={(event) => setDocumentClientName(event.target.value)} /></label>
              <label>VIN lu<input value={documentVehicleVin} maxLength={17} onChange={(event) => setDocumentVehicleVin(event.target.value.toUpperCase())} /></label>
              <label>Immatriculation lue<input value={documentRegistration} onChange={(event) => setDocumentRegistration(event.target.value.toUpperCase())} /></label>
              <label>Nombre de pages<input type="number" min={1} step={1} value={documentPageCount} onChange={(event) => setDocumentPageCount(event.target.value)} /></label>
              <label>Pagination<select value={documentPaginationStatus} onChange={(event) => setDocumentPaginationStatus(event.target.value as MaintenanceRecordInput["document_pagination_status"])}><option value="complete">Complète</option><option value="partial">Incomplète</option><option value="inferred">Déduite, à vérifier</option><option value="unknown">Non indiquée</option></select></label>
              <label>N° de dossier<input value={documentDossierId} onChange={(event) => setDocumentDossierId(event.target.value)} /></label>
            </div>
          </section>}

          <button type="button" className="maintenance-disclosure" onClick={() => setShowParts((value) => !value)}><span><strong>Pièces et consommables</strong><small>{parts.filter((part) => part.name.trim()).length || "Aucune"} pièce(s) renseignée(s)</small></span><b>{showParts ? "Masquer" : "Afficher"}</b></button>
          {showParts && <div className="maintenance-parts-editor">
            <header><div><strong>Pièces et consommables</strong><small>Le rôle indique ce qui a réellement été monté, consommé, retourné ou utilisé comme outil.</small></div><button type="button" className="secondary-button" onClick={() => setParts((current) => [...current, emptyPart()])}>＋ Ajouter une pièce</button></header>
            {parts.map((part, index) => <div className="maintenance-part-row" key={index}>
              <label>Désignation<input value={part.name} onChange={(event) => updatePart(index, "name", event.target.value)} /></label>
              <label>Rôle<select value={part.usage} onChange={(event) => updatePart(index, "usage", event.target.value)}><option value="installed">Montée</option><option value="consumed">Consommée</option><option value="tool">Outillage</option><option value="shipping">Livraison</option><option value="discount">Remise</option><option value="not_used">Non utilisée</option><option value="returned">Retournée</option></select></label>
              <label>Fabricant<input value={part.manufacturer} onChange={(event) => updatePart(index, "manufacturer", event.target.value)} /></label>
              <label>Référence pièce<input value={part.part_number} onChange={(event) => updatePart(index, "part_number", event.target.value)} /></label>
              <label>N° de série<input value={part.serial_number} onChange={(event) => updatePart(index, "serial_number", event.target.value)} /></label>
              <label>Ancienne référence<input value={part.removed_part_number} onChange={(event) => updatePart(index, "removed_part_number", event.target.value)} /></label>
              <label>Ancien n° de série<input value={part.removed_serial_number} onChange={(event) => updatePart(index, "removed_serial_number", event.target.value)} /></label>
              <label>Qté<input type="number" min="0.01" step="0.01" value={part.quantity} onChange={(event) => updatePart(index, "quantity", event.target.value)} /></label>
              <label>Prix unitaire (€)<input type="number" min={0} step="0.01" value={part.unit_price} onChange={(event) => updatePart(index, "unit_price", event.target.value)} /></label>
              <label>Position<select value={part.position} onChange={(event) => updatePart(index, "position", event.target.value)}><option value="">Non précisée</option><option value="front">Avant</option><option value="rear">Arrière</option><option value="front_left">Avant gauche</option><option value="front_right">Avant droite</option><option value="rear_left">Arrière gauche</option><option value="rear_right">Arrière droite</option><option value="engine">Moteur</option><option value="cabin">Habitacle</option><option value="other">Autre</option></select></label>
              <label>Système normalisé<input value={part.system_code} onChange={(event) => updatePart(index, "system_code", event.target.value)} placeholder="brakes.front" /></label>
              <label>Garantie jusqu’au<input type="date" value={part.warranty_until} onChange={(event) => updatePart(index, "warranty_until", event.target.value)} /></label>
              <label>Note<input value={part.note} onChange={(event) => updatePart(index, "note", event.target.value)} /></label>
              <button type="button" className="maintenance-remove-part" disabled={parts.length === 1} onClick={() => setParts((current) => current.filter((_, partIndex) => partIndex !== index))}>Retirer</button>
            </div>)}
          </div>}

          <button type="button" className="maintenance-disclosure" onClick={() => setShowRecommendations((value) => !value)}><span><strong>Diagnostics, recommandations et rappels</strong><small>{recommendations.length || "Aucune"} recommandation(s)</small></span><b>{showRecommendations ? "Masquer" : "Afficher"}</b></button>
          {showRecommendations && <div className="maintenance-recommendation-editor">
            <header><div><strong>Diagnostics, recommandations et rappels</strong><small>Exemple : vérifier les plaquettes 500 km après le diagnostic.</small></div><button type="button" className="secondary-button" onClick={() => setRecommendations((current) => [...current, emptyRecommendation(mileageKm)])}>＋ Ajouter une recommandation</button></header>
            {recommendations.map((recommendation, index) => <div className="maintenance-part-row" key={index}>
              <label>Recommandation<input value={recommendation.title} onChange={(event) => updateRecommendation(index, "title", event.target.value)} placeholder="Ex. Rotules axiales à remplacer" /></label>
              <label>Statut<select value={recommendation.status} onChange={(event) => updateRecommendation(index, "status", event.target.value)}><option value="open">À faire</option><option value="monitoring">À surveiller</option><option value="completed">Réalisée</option><option value="dismissed">Classée sans suite</option></select></label>
              <label>Km du constat<input type="number" min={0} value={recommendation.recommended_at_km} onChange={(event) => updateRecommendation(index, "recommended_at_km", event.target.value)} /></label>
              <label>Rappel après + km<input type="number" min={1} value={recommendation.follow_up_after_km} onChange={(event) => updateRecommendation(index, "follow_up_after_km", event.target.value)} placeholder="500" /></label>
              <label>Échéance kilométrique<input type="number" min={0} value={recommendation.due_mileage_km} onChange={(event) => updateRecommendation(index, "due_mileage_km", event.target.value)} /></label>
              <label>Échéance date<input type="date" value={recommendation.due_date} onChange={(event) => updateRecommendation(index, "due_date", event.target.value)} /></label>
              <label>Détail<input value={recommendation.details} onChange={(event) => updateRecommendation(index, "details", event.target.value)} /></label>
              <button type="button" className="maintenance-remove-part" onClick={() => setRecommendations((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Retirer</button>
            </div>)}
          </div>}

          <label className="maintenance-notes maintenance-simple-notes">Compte rendu ou notes<textarea rows={4} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Ce qui a été fait, résultat du diagnostic, remarque utile…" /></label>
          {formError && <p className="inline-alert">{formError}</p>}
          <div className="maintenance-form-actions"><button type="button" className="ghost-button" onClick={resetForm}>Annuler</button><button className="primary-button" disabled={busy} onClick={() => void handleSubmit()}>{busy ? "Enregistrement…" : editingRecord ? "Enregistrer les corrections" : "Enregistrer l’intervention"}</button></div>
          </div>

          {previewUrl && <aside className="maintenance-document-preview">
            <header><div><span className="eyebrow">Document source</span><strong>{previewDocument?.original_name ?? documents[0]?.name}</strong><small>{previewDocument ? `${previewDocument.page_count} page(s) · PDF recadré${previewDocument.source_names.length ? ` · ${previewDocument.source_names.length} source(s) conservée(s)` : ""}` : previewMediaType === "application/pdf" ? "PDF à valider" : "Photo source · elle sera recadrée et convertie en PDF"}</small></div>{previewDocument && <a href={previewUrl} target="_blank" rel="noreferrer">Ouvrir ↗</a>}</header>
            {previewMediaType === "application/pdf" ? <iframe src={previewUrl} title="Document de l’intervention" /> : <img src={previewUrl} alt="Document à valider" />}
          </aside>}
          </div>
        </div>
      )}

      {records.length > 0 && <div className="maintenance-history-toolbar"><input type="search" value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} placeholder="Rechercher une pièce, une facture, un garage…" aria-label="Rechercher dans l’historique" /><select value={historyFilter} onChange={(event) => setHistoryFilter(event.target.value as typeof historyFilter)} aria-label="Filtrer l’historique"><option value="all">Tout l’historique</option><option value="attention">À vérifier ou à faire</option><option value="invoices">Avec facture</option></select><span>{visibleRecords.length} / {records.length}</span></div>}

      {records.length === 0 ? <EmptyState title="Aucune intervention mécanique" text="Ajoute la première facture ou opération réalisée sur ce véhicule." /> : visibleRecords.length === 0 ? <EmptyState title="Aucun résultat" text="Modifie la recherche ou le filtre pour retrouver l’intervention." /> : <div className="maintenance-record-list">{visibleRecords.map((record) => {
        const performer = record.performer_provider_id ? providersById.get(record.performer_provider_id) : null;
        return <article className={`maintenance-record-card ${record.record_status === "draft" ? "draft" : ""}`} key={record.id}>
          <header><div><span>{record.performed_at ? `Réalisé le ${displayDate(record.performed_at)}` : `Acheté le ${displayDate(record.purchased_at)}`}</span><h3>{record.title}</h3></div><strong>{record.mileage_km == null ? "Kilométrage inconnu" : `${record.mileage_source === "history_estimate" ? "≈ " : ""}${record.mileage_km.toLocaleString("fr-FR")} km`}</strong></header>
          <div className="maintenance-record-meta"><span>{record.record_status === "draft" ? "À confirmer" : record.category}</span>{record.purchased_at && <span>Achat {displayDate(record.purchased_at)}</span>}{record.performed_at_source === "invoice_date_assumed" && <span>Pose déduite de la facture</span>}{performer && <span>Réalisé par {providerLabel(performer)}</span>}{record.performed_by === "owner" && <span>Réalisé par le propriétaire</span>}{record.invoice_number && <span>Facture {record.invoice_number}</span>}{typeof record.invoice_total === "number" && <b>{formatMoney(record.invoice_total, record.currency)}</b>}<button type="button" className="ghost-button" onClick={() => startEdit(record)}>Corriger</button></div>
          <details className="maintenance-record-details"><summary>Voir le détail · {record.parts.length} pièce(s) · {record.documents.length} justificatif(s)</summary><div className="maintenance-record-details-body">
          {record.mileage_note && <p className="maintenance-record-mileage-note">{record.mileage_note}</p>}
          {(record.document_client_name || record.document_vehicle_vin || record.document_registration || record.document_page_count) && <div className="maintenance-record-meta">{record.document_client_name && <span>Client : {record.document_client_name}</span>}{record.document_vehicle_vin && <span>VIN lu : {record.document_vehicle_vin}</span>}{record.document_registration && <span>Immat. {record.document_registration}</span>}{record.document_page_count && <span>{record.document_page_count} page(s) · {record.document_pagination_status}</span>}</div>}
          {record.parts.length > 0 && <div className="maintenance-record-parts">{record.parts.map((part, index) => <div key={`${part.name}-${index}`}><strong>{part.quantity} × {part.name}</strong><span>{[part.usage !== "installed" && part.usage, part.manufacturer, part.part_number && `réf. ${part.part_number}`, part.serial_number && `série ${part.serial_number}`, part.position].filter(Boolean).join(" · ") || "Référence non renseignée"}</span>{part.warranty_until && <small>Garantie jusqu’au {displayDate(part.warranty_until)}</small>}</div>)}</div>}
          {record.cost_lines.length > 0 && <details className="maintenance-cost-lines"><summary>{record.cost_lines.length} ligne(s) de facture</summary><div>{record.cost_lines.map((line, index) => <p key={`${line.description}-${index}`}><span>{line.quantity ? `${line.quantity} × ` : ""}{line.description}{line.reference ? ` · réf. ${line.reference}` : ""}</span><strong>{typeof line.amount_incl_tax === "number" ? formatMoney(line.amount_incl_tax, record.currency) : typeof line.amount_excl_tax === "number" ? `${formatMoney(line.amount_excl_tax, record.currency)} HT` : "—"}</strong></p>)}</div></details>}
          {record.notes && <p>{record.notes}</p>}
          {record.recommendations.length > 0 && <div className="maintenance-recommendations"><strong>Recommandations et suivi</strong>{record.recommendations.map((recommendation, index) => <div className={recommendation.status} key={`${recommendation.title}-${index}`}><span>{recommendation.title}</span><small>{[recommendation.status === "completed" ? recommendation.auto_managed ? "Réalisée · validée automatiquement" : "Réalisée manuellement" : recommendation.status === "monitoring" ? "À surveiller" : recommendation.status === "dismissed" ? "Classée sans suite" : "À faire", recommendation.due_mileage_km && `avant ${recommendation.due_mileage_km.toLocaleString("fr-FR")} km`, recommendation.follow_up_after_km && `contrôle après +${recommendation.follow_up_after_km.toLocaleString("fr-FR")} km`, recommendation.due_date && displayDate(recommendation.due_date)].filter(Boolean).join(" · ")}</small>{recommendation.completion_reason && <small className="maintenance-completion-proof">✓ {recommendation.completion_reason}</small>}<div className="maintenance-recommendation-actions">{recommendation.status === "open" || recommendation.status === "monitoring" ? <><button type="button" disabled={busy} onClick={() => void onSetRecommendationStatus(record.id, index, "completed")}>✓ Marquer réalisée</button><button type="button" disabled={busy} onClick={() => void onSetRecommendationStatus(record.id, index, "dismissed")}>Classer sans suite</button></> : <button type="button" disabled={busy} onClick={() => void onSetRecommendationStatus(record.id, index, "open")}>↶ Rouvrir</button>}</div></div>)}</div>}
          {record.import_snapshot && <details className="maintenance-import-proof"><summary>Import d’origine et champs à vérifier</summary>{record.import_snapshot.warnings.map((warning) => <span key={warning}>{warning}</span>)}<pre>{record.import_snapshot.text_excerpt}</pre></details>}
          {record.documents.length > 0 && <footer>{record.documents.map((document) => <a href={`${API_BASE}${document.download_url}?vin=${encodeURIComponent(record.vin)}&v=${document.sha256.slice(0, 12)}`} target="_blank" rel="noreferrer" key={document.id}>↗ {document.original_name}<small>{document.page_count} page(s) · {(document.size_bytes / 1024 / 1024).toFixed(1)} Mo{document.normalized ? " · PDF recadré" : ""} · SHA‑256 {document.sha256.slice(0, 12)}…</small></a>)}</footer>}
          <div className="maintenance-add-document"><label>Ajouter une facture / photo<input type="file" multiple accept="application/pdf,image/jpeg,image/png,image/webp" onChange={(event) => setPendingDocuments((current) => ({ ...current, [record.id]: Array.from(event.target.files ?? []) }))} /></label><button type="button" className="ghost-button" disabled={busy || !(pendingDocuments[record.id]?.length)} onClick={async () => { await onAddDocuments(record.id, pendingDocuments[record.id] ?? []); setPendingDocuments((current) => ({ ...current, [record.id]: [] })); }}>Joindre</button></div>
          <small className="maintenance-revision">Révision {record.revision} · enregistré le {new Date(record.created_at).toLocaleDateString("fr-FR")}</small>
          </div></details>
        </article>;
      })}</div>}
    </section>
  );
}
