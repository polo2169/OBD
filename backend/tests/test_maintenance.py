import pytest

from app.diagnostic.maintenance import (
    maintenance_catalog,
    require_vehicle_validated_service,
)


@pytest.mark.parametrize("profile", ["fiat_500_generic", "peugeot_308_t9_2018"])
def test_maintenance_catalog_exposes_full_matrix_without_unvalidated_execution(profile):
    catalog = maintenance_catalog(profile)

    assert catalog["vehicle_profile"] == profile
    assert catalog["service_count"] >= 28
    assert len({service["key"] for service in catalog["services"]}) == catalog["service_count"]
    assert not catalog["execution_enabled"]
    assert not any(service["execution_enabled"] for service in catalog["services"])
    assert all(isinstance(note, str) for note in catalog["notes"])
    assert any(protocol["key"] == "iso15765_can" and protocol["supported"] for protocol in catalog["protocol_coverage"])
    assert any(protocol["key"] == "can_fd" and not protocol["supported"] for protocol in catalog["protocol_coverage"])


def test_fiat_gasoline_hides_inapplicable_emissions_services():
    catalog = maintenance_catalog("fiat_500_generic")
    services = {service["key"]: service for service in catalog["services"]}

    assert services["adblue_reset"]["applicability"] == "not_applicable"
    assert services["dpf_regeneration"]["applicability"] == "not_applicable"
    assert services["oil_service_reset"]["applicability"] == "applicable"
    assert services["battery_adaptation"]["applicability"] == "if_equipped"


def test_unvalidated_service_guard_refuses_transmission():
    with pytest.raises(PermissionError, match="aucune séquence constructeur validée"):
        require_vehicle_validated_service("peugeot_308_t9_2018", "oil_service_reset")
