import { EmptyState } from "../components/ui";
import type { MaintenanceCatalog, MaintenanceService } from "../types";

type MaintenanceScreenProps = {
  catalog: MaintenanceCatalog | null;
  categories: string[];
  selectedCategory: string;
  services: MaintenanceService[];
  onCategoryChange: (category: string) => void;
  onUnavailableProcedure: () => void;
};

export function MaintenanceScreen({
  catalog,
  categories,
  selectedCategory,
  services,
  onCategoryChange,
  onUnavailableProcedure,
}: MaintenanceScreenProps) {
  if (!catalog) {
    return <EmptyState title="Catalogue en chargement" text="Lecture des capacités du profil véhicule actif." />;
  }

  const applicabilityLabel: Record<MaintenanceService["applicability"], string> = {
    applicable: "Applicable",
    if_equipped: "Selon équipement",
    not_applicable: "Non applicable",
    unknown: "À rechercher",
  };
  const statusLabel: Record<MaintenanceService["implementation_status"], string> = {
    vehicle_validated: "Validé véhicule",
    procedure_required: "Procédure à valider",
    equipment_confirmation_required: "Équipement à confirmer",
    not_applicable: "Masqué sur ce profil",
    research_required: "Documentation requise",
  };

  return (
    <>
      <section className="panel maintenance-overview">
        <div className="section-heading">
          <div><span className="eyebrow">{catalog.manufacturer} {catalog.model}</span><h2>{catalog.service_count} services référencés</h2><p>Le catalogue n'autorise jamais une trame tant que la procédure exacte et ses prérequis ne sont pas validés sur le véhicule.</p></div>
          <span className={`status-pill ${catalog.execution_enabled ? "good" : "neutral"}`}><i />{catalog.execution_enabled ? "Procédures validées disponibles" : "Catalogue sécurisé"}</span>
        </div>
        <div className="maintenance-protocol-grid">
          {catalog.protocol_coverage.map((protocol) => <article className={protocol.supported ? "supported" : "missing"} key={protocol.key}><strong>{protocol.name}</strong><span>{protocol.supported ? "Pris en charge" : "Matériel requis"}</span><p>{protocol.detail}</p></article>)}
        </div>
        {catalog.notes.map((note) => <p className="inline-alert" key={note}>{note}</p>)}
      </section>

      <section className="panel maintenance-catalog-panel">
        <div className="section-heading"><div><span className="eyebrow">Matrice d'applicabilité</span><h2>Fonctions Fiat / Peugeot</h2></div></div>
        <div className="sensor-category-tabs">
          {categories.map((category) => <button className={selectedCategory === category ? "active" : ""} key={category} onClick={() => onCategoryChange(category)}>{category}</button>)}
        </div>
        <div className="maintenance-service-grid">
          {services.map((service) => (
            <article className={`${service.applicability} risk-${service.risk}`} key={service.key}>
              <header><span>{service.category}</span><b>{applicabilityLabel[service.applicability]}</b></header>
              <h3>{service.name}</h3>
              <p>{service.description}</p>
              <small>{service.reason}</small>
              <footer><span>{statusLabel[service.implementation_status]}</span><button className="secondary-button" disabled={!service.execution_enabled} onClick={onUnavailableProcedure}>{service.execution_enabled ? "Ouvrir la procédure" : "Verrouillé"}</button></footer>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
