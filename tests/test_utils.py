"""Tests for MyEnergy parsing and data refresh behavior."""

import pytest
from bs4 import BeautifulSoup
import voluptuous as vol

from custom_components.myenergy.sensor import ComponentData
from custom_components.myenergy.utils import (
    ComponentSession,
    ContractType,
    check_settings,
    _build_section_name,
    _extract_euro_value,
    _parse_new_results_cards,
    validate_manual_results_url,
)


def test_extract_euro_value_parses_eu_number_format():
    """Euro parser should handle thousands separators and comma decimals."""
    assert _extract_euro_value("€ 1.234,56/jaar") == 1234.56


def test_extract_euro_value_returns_none_without_amount():
    """Euro parser should return None when no value is present."""
    assert _extract_euro_value("no price here") is None


def test_build_section_name_maps_known_fuel_types():
    """Section helper should map fuel slugs to expected section names."""
    assert _build_section_name("elektriciteit") == "Elektriciteit"
    assert _build_section_name("aardgas") == "Aardgas"


def test_parse_new_results_cards_parses_first_valid_card():
    """Parser should return first valid provider card with annual price details."""
    html = """
    <section>
      <article>
        <img alt="Logo Mega" />
        <h3>Smart Flex</h3>
        <p>€ 95,00 / maand</p>
        <p>€ 1.140,00 / jaar</p>
      </article>
      <article>
        <img alt="Logo Other" />
        <h3>Ignored Second</h3>
        <p>€ 99,00 / maand</p>
        <p>€ 1.188,00 / jaar</p>
      </article>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")

    parsed = _parse_new_results_cards(
        soup,
        "https://example.com/results",
        3800,
        "Elektriciteit",
    )

    assert "Elektriciteit" in parsed
    assert len(parsed["Elektriciteit"]) == 1
    card = parsed["Elektriciteit"][0]
    assert card["provider"] == "Mega"
    assert card["name"] == "Smart Flex"
    assert card["url"] == "https://example.com/results"
    assert card["Jaarlijkse kostprijs"] == [
        "30.00 c€/kWh",
        "3800 kWh/jaar",
        "€ 1140.00/jaar",
    ]


def test_parse_new_results_cards_returns_empty_for_invalid_cards():
    """Parser should return empty dict when required fields are missing."""
    html = """
    <section>
      <article>
        <h3>No provider image</h3>
        <p>€ 1.140,00 / jaar</p>
      </article>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")

    parsed = _parse_new_results_cards(
        soup,
        "https://example.com/results",
        3800,
        "Elektriciteit",
    )

    assert parsed == {}


@pytest.mark.asyncio
async def test_component_data_keeps_contract_keys_for_empty_results(hass):
    """Refresh should keep F/V keys even when parser returns no data."""
    config = {
        "postalcode": "1000",
        "electricity_digital_counter": False,
        "day_electricity_consumption": 1000,
        "night_electricity_consumption": 0,
        "excl_night_electricity_consumption": 0,
        "solar_panels": False,
        "electricity_injection": 0,
        "electricity_injection_night": 0,
        "electricity_provider": "No provider",
        "inverter_power": 0,
        "combine_elec_and_gas": False,
        "gas_consumption": 0,
        "gas_provider": "No provider",
        "directdebit_invoice": True,
        "email_invoice": True,
        "online_support": True,
        "electric_car": False,
    }

    component_data = ComponentData(config, hass)

    def _empty_get_data(_cfg, _contract_type):
        return {}

    component_data._session.get_data = _empty_get_data

    await component_data._forced_update()

    assert component_data._details["F"] == {}
    assert component_data._details["V"] == {}
    assert component_data._refresh_required is True


def test_manual_results_url_falls_back_to_generated_results_url():
    """Session should fallback when manual URL has no parseable offer cards."""
    config = {
        "manual_results_url": "https://example.com/manual",
        "postalcode": "1000",
        "electricity_digital_counter": False,
        "day_electricity_consumption": 3800,
        "night_electricity_consumption": 0,
        "excl_night_electricity_consumption": 0,
        "solar_panels": False,
        "electricity_injection": 0,
        "electricity_injection_night": 0,
        "electricity_provider": "No provider",
        "inverter_power": 0,
        "combine_elec_and_gas": False,
        "gas_consumption": 0,
        "gas_provider": "No provider",
        "directdebit_invoice": True,
        "email_invoice": True,
        "online_support": True,
        "electric_car": False,
    }

    class _Response:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

        def raise_for_status(self):
            return None

    class _FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout=30, allow_redirects=True):
            self.calls.append(url)
            if url == "https://example.com/manual":
                # No article cards in manual page -> forces fallback.
                return _Response("<html><body><h1>Step page</h1></body></html>")

            # Generated URL response with valid article card.
            return _Response(
                """
                <section>
                  <article>
                    <img alt=\"Logo Mega\" />
                    <h3>Smart Flex</h3>
                    <p>€ 95,00 / maand</p>
                    <p>€ 1.140,00 / jaar</p>
                  </article>
                </section>
                """
            )

    component_session = ComponentSession()
    component_session.s = _FakeSession()

    result = component_session.get_data(config, ContractType.FIXED)

    assert isinstance(result, dict)
    assert len(component_session.s.calls) == 2


def test_validate_manual_results_url_rejects_step_url():
    """Step URLs should be rejected because they are not result pages."""
    with pytest.raises(vol.Invalid):
        validate_manual_results_url(
            "https://www.mijnenergie.be/vergelijking/stap-3/3b5e4543-e1f8-4215-adf3-45fc929910ab"
        )


def test_validate_manual_results_url_accepts_non_step_url():
    """Non-step URLs should pass validation."""
    assert (
        validate_manual_results_url(
            "https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe"
        )
        is True
    )


def test_check_settings_rejects_invalid_manual_results_url():
    """Settings validation should fail fast for step URLs."""
    config = {
        "postalcode": "1000",
        "manual_results_url": "https://www.mijnenergie.be/vergelijking/stap-2/abc",
    }

    with pytest.raises(vol.Invalid):
        check_settings(config, None)
