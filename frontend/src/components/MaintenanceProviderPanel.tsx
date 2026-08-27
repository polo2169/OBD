import { useState } from "react";

import type { ServiceProvider, ServiceProviderInput } from "../types";


type MaintenanceProviderPanelProps = {
  providers: ServiceProvider[];
  busy: boolean;
  onCreate: (entry: ServiceProviderInput) => Promise<ServiceProvider | null>;
  onUpdate: (providerId: string, entry: ServiceProviderInput) => Promise<ServiceProvider | null>;
};

const emptyProvider = (): ServiceProviderInput => ({
  kind: "garage",
  legal_name: "",
  display_name: null,
  network: null,
  siren: null,
  siret: null,
  vat_number: null,
  address_line1: null,
  address_line2: null,
  postal_code: null,
  city: null,
  country_code: "FR",
  phone: null,
  email: null,
  website: null,
  latitude: null,
  longitude: null,
  aliases: [],
  verified_by_user: true,
});

const textValue = (value: string) => value.trim() || null;

export function MaintenanceProviderPanel({ providers, busy, onCreate, onUpdate }: MaintenanceProviderPanelProps) {
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ServiceProviderInput>(emptyProvider);
  const [error, setError] = useState("");

  function edit(provider: ServiceProvider) {
    const { id: _id, created_at: _created, updated_at: _updated, revision: _revision, ...input } = provider;
    setDraft(input);
    setEditingId(provider.id);
    setError("");
    setDirectoryOpen(true);
    setOpen(true);
  }

  function reset() {
    setDraft(emptyProvider());
    setEditingId(null);
    setError("");
    setOpen(false);
  }

  async function save() {
    if (!draft.legal_name.trim()) {
      setError("Le nom du professionnel est obligatoire.");
      return;
    }
    const normalized: ServiceProviderInput = {
      ...draft,
      legal_name: draft.legal_name.trim(),
      display_name: textValue(draft.display_name ?? ""),
      network: textValue(draft.network ?? ""),
      siren: textValue(draft.siren ?? ""),
      siret: textValue(draft.siret ?? ""),
      vat_number: textValue(draft.vat_number ?? ""),
      address_line1: textValue(draft.address_line1 ?? ""),
      address_line2: textValue(draft.address_line2 ?? ""),
      postal_code: textValue(draft.postal_code ?? ""),
      city: textValue(draft.city ?? ""),
      phone: textValue(draft.phone ?? ""),
      email: textValue(draft.email ?? ""),
      website: textValue(draft.website ?? ""),
      aliases: draft.aliases.filter(Boolean),
    };
    const saved = editingId ? await onUpdate(editingId, normalized) : await onCreate(normalized);
    if (saved) reset();
  }

  const set = <K extends keyof ServiceProviderInput>(key: K, value: ServiceProviderInput[K]) => (
    setDraft((current) => ({ ...current, [key]: value }))
  );

  return (
    <section className="panel maintenance-provider-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Annuaire réutilisable</span>
          <h2>Garages &amp; fournisseurs</h2>
          <p>Les coordonnées sont normalisées une seule fois, puis reliées aux factures et interventions.</p>
        </div>
        <button className="secondary-button" onClick={() => { if (directoryOpen) reset(); setDirectoryOpen((value) => !value); }}>
          {directoryOpen ? "Fermer l’annuaire" : `Gérer (${providers.length})`}
        </button>
      </div>

      {directoryOpen && <div className="maintenance-provider-toolbar"><strong>{providers.length} professionnel(s) enregistré(s)</strong><button className="secondary-button" onClick={() => open ? reset() : setOpen(true)}>{open ? "Annuler" : "＋ Ajouter"}</button></div>}

      {directoryOpen && providers.length > 0 && (
        <div className="maintenance-provider-list">
          {providers.map((provider) => (
            <button type="button" key={provider.id} onClick={() => edit(provider)}>
              <strong>{provider.display_name || provider.legal_name}</strong>
              <span>{[provider.kind.replaceAll("_", " "), provider.postal_code, provider.city, provider.phone].filter(Boolean).join(" · ")}</span>
            </button>
          ))}
        </div>
      )}

      {directoryOpen && open && (
        <div className="maintenance-provider-form">
          <div className="maintenance-form-grid">
            <label>Type<select value={draft.kind} onChange={(event) => set("kind", event.target.value as ServiceProviderInput["kind"])}><option value="garage">Garage</option><option value="dealership">Concession</option><option value="inspection_center">Contrôle technique</option><option value="body_shop">Carrosserie</option><option value="tire_shop">Pneumatiques</option><option value="parts_supplier">Fournisseur de pièces</option><option value="other">Autre</option></select></label>
            <label>Raison sociale *<input value={draft.legal_name} onChange={(event) => set("legal_name", event.target.value)} /></label>
            <label>Nom affiché<input value={draft.display_name ?? ""} onChange={(event) => set("display_name", event.target.value)} /></label>
            <label>Réseau / enseigne<input value={draft.network ?? ""} onChange={(event) => set("network", event.target.value)} /></label>
            <label>SIREN<input value={draft.siren ?? ""} onChange={(event) => set("siren", event.target.value)} /></label>
            <label>SIRET<input value={draft.siret ?? ""} onChange={(event) => set("siret", event.target.value)} /></label>
            <label>TVA intracommunautaire<input value={draft.vat_number ?? ""} onChange={(event) => set("vat_number", event.target.value)} /></label>
            <label>Adresse<input value={draft.address_line1 ?? ""} onChange={(event) => set("address_line1", event.target.value)} /></label>
            <label>Complément<input value={draft.address_line2 ?? ""} onChange={(event) => set("address_line2", event.target.value)} /></label>
            <label>Code postal<input value={draft.postal_code ?? ""} onChange={(event) => set("postal_code", event.target.value)} /></label>
            <label>Ville<input value={draft.city ?? ""} onChange={(event) => set("city", event.target.value)} /></label>
            <label>Téléphone<input value={draft.phone ?? ""} onChange={(event) => set("phone", event.target.value)} /></label>
            <label>E-mail<input type="email" value={draft.email ?? ""} onChange={(event) => set("email", event.target.value)} /></label>
            <label>Site web<input value={draft.website ?? ""} onChange={(event) => set("website", event.target.value)} /></label>
          </div>
          {error && <p className="inline-alert">{error}</p>}
          <button className="primary-button" disabled={busy} onClick={() => void save()}>{editingId ? "Mettre à jour" : "Enregistrer le professionnel"}</button>
        </div>
      )}
    </section>
  );
}
