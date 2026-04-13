"""Tests for MyEnergy parsing and data refresh behavior."""

import pytest
import requests
from bs4 import BeautifulSoup

from custom_components.myenergy.sensor import ComponentData
from custom_components.myenergy.utils import (
    ComparisonUnavailableError,
    ComponentSession,
    ContractType,
    _build_simulation_payload,
    check_settings,
    _build_section_name,
    _extract_euro_value,
    _parse_simulation_results,
    _parse_new_results_cards,
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


def test_parse_new_results_cards_parses_legacy_card_layout():
    """Parser should handle legacy card-energy-details layout used on some result pages."""
    html = """
    <section id="RestultatElec">
      <div class="card card-energy-details border border-light">
        <div class="provider-logo-lg">
          <img alt="Logo Mega" />
        </div>
        <li class="list-inline-item large-body-font-size text-strong mb-2 mb-sm-0">Legacy Flex</li>
        <table>
          <tr><th>Jaarlijkse kostprijs</th><td>€ 1.140,00</td></tr>
        </table>
      </div>
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
    card = parsed["Elektriciteit"][0]
    assert card["provider"] == "Mega"
    assert card["name"] == "Legacy Flex"
    assert card["Jaarlijkse kostprijs"] == [
        "30.00 c€/kWh",
        "3800 kWh/jaar",
        "€ 1140.00/jaar",
    ]


def test_parse_new_results_cards_prefers_yearly_context_over_max_value():
        """Annual selection should prioritize yearly-context value over unrelated larger amounts."""
        html = """
        <section>
            <article>
                <img alt="Logo Mega" />
                <h3>Context Aware Plan</h3>
                <p>Special bonus: € 2.500,00</p>
                <p>Estimated yearly amount € 1.140,00</p>
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
        card = parsed["Elektriciteit"][0]
        assert card["Jaarlijkse kostprijs"] == [
                "30.00 c€/kWh",
                "3800 kWh/jaar",
                "€ 1140.00/jaar",
        ]


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


def test_check_settings_accepts_minimal_valid_config():
    """Settings validation should pass for valid postal code based config."""
    config = {"postalcode": "1000"}
    assert check_settings(config, None) is True


def test_generated_url_next_not_found_raises_comparison_unavailable():
    """Generated URL not-found page should raise a non-retryable comparison error."""
    config = {
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
        def __init__(self, text="", json_value=None):
            self.text = text
            self.status_code = 200
            self._json_value = json_value

        def raise_for_status(self):
            return None

        def json(self):
            return self._json_value

    class _FakeSession:
        def get(self, url, timeout=30, allow_redirects=True):
            if "zone/localities" in url:
                return _Response(json_value=[{"id": 7, "zipCode": 1000}])
            return _Response("<html><head><title>Pagina niet gevonden</title></head><body>NEXT_NOT_FOUND</body></html>")

        def post(self, url, json=None, timeout=30, allow_redirects=True):
            # Force legacy fallback path by returning empty API results.
            return _Response(json_value={"results": [], "forwardResults": []})

    component_session = ComponentSession()
    component_session.s = _FakeSession()

    with pytest.raises(ComparisonUnavailableError):
        component_session.get_data(config, ContractType.FIXED)


def test_simulation_http_422_falls_back_to_generated_url_parsing():
    """Simulation API validation errors should not break generated URL fallback."""
    config = {
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
        def __init__(self, text="", json_value=None, status_code=200):
            self.text = text
            self.status_code = status_code
            self._json_value = json_value

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(
                    f"{self.status_code} error", response=self
                )
            return None

        def json(self):
            return self._json_value

    class _FakeSession:
        def get(self, url, timeout=30, allow_redirects=True):
            if "zone/localities" in url:
                return _Response(json_value=[{"id": 7, "zipCode": 1000}])
            return _Response(
                text="""
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

        def post(self, url, json=None, timeout=30, allow_redirects=True):
            return _Response(
                text='{"message":"validation failed"}',
                json_value={"message": "validation failed"},
                status_code=422,
            )

    component_session = ComponentSession()
    component_session.s = _FakeSession()

    result = component_session.get_data(config, ContractType.FIXED)

    assert "Elektriciteit" in result
    offer = result["Elektriciteit"][0]
    assert offer["provider"] == "Mega"
    assert offer["name"] == "Smart Flex"


def test_locality_api_error_falls_back_to_generated_url_parsing():
    """Locality lookup failures should skip simulation and keep HTML fallback alive."""
    config = {
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
        def __init__(self, text="", json_value=None, status_code=200):
            self.text = text
            self.status_code = status_code
            self._json_value = json_value

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(
                    f"{self.status_code} error", response=self
                )
            return None

        def json(self):
            return self._json_value

    class _FakeSession:
        def get(self, url, timeout=30, allow_redirects=True):
            if "zone/localities" in url:
                raise requests.RequestException("locality endpoint unavailable")
            return _Response(
                text="""
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

        def post(self, url, json=None, timeout=30, allow_redirects=True):
            raise AssertionError("simulation API should not be called after locality failure")

    component_session = ComponentSession()
    component_session.s = _FakeSession()

    result = component_session.get_data(config, ContractType.FIXED)

    assert "Elektriciteit" in result
    offer = result["Elektriciteit"][0]
    assert offer["provider"] == "Mega"
    assert offer["name"] == "Smart Flex"


def test_simulation_422_falls_back_to_html_parsing():
    """When simulation API returns 422, falls back to HTML parsing."""
    config = {
        "postalcode": "1000",
        "electricity_digital_counter": False,
        "day_electricity_consumption": 2000,
        "night_electricity_consumption": 1500,
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
        def __init__(self, text="", json_value=None, status_code=200):
            self.text = text
            self.status_code = status_code
            self._json_value = json_value

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(
                    f"{self.status_code} error", response=self
                )
            return None

        def json(self):
            return self._json_value

    html_called = False

    class _FakeSession:
        def __init__(self):
            self.post_payloads = []

        def get(self, url, timeout=30, allow_redirects=True):
            nonlocal html_called
            if "zone/localities" in url:
                return _Response(json_value=[{"id": 7, "zipCode": 1000}])
            # HTML fallback path
            html_called = True
            return _Response(text="<html>NEXT_NOT_FOUND</html>")

        def post(self, url, json=None, timeout=30, allow_redirects=True):
            self.post_payloads.append(json)
            return _Response(
                text='{"details":[{"propertyPath":"meterType"}],"statusCode":422}',
                status_code=422,
            )

    component_session = ComponentSession()
    component_session.s = _FakeSession()

    with pytest.raises(ComparisonUnavailableError):
        component_session.get_data(config, ContractType.FIXED)

    # meterType sent as string directly
    assert component_session.s.post_payloads[0]["meterType"] == "2"
    # Only one POST (no retry)
    assert len(component_session.s.post_payloads) == 1


def test_build_simulation_payload_mono_without_gas_or_solar():
    """Payload builder should match API validation for mono electricity setup."""
    config = {
        "postalcode": "1000",
        "day_electricity_consumption": 3500,
        "night_electricity_consumption": 0,
        "excl_night_electricity_consumption": 0,
        "electricity_injection": 0,
        "electricity_injection_night": 0,
        "gas_consumption": 0,
        "solar_panels": False,
        "electricity_digital_counter": False,
        "electric_car": False,
    }

    locality = {"id": 7, "zipCode": 1000}
    payload = _build_simulation_payload(config, locality)

    assert payload["meterType"] == "1"
    assert payload["eAnnualDayConsumption"] == 3500
    assert "eAnnualNightConsumption" not in payload
    assert "eAnnualDayInjection" not in payload
    assert "gAnnualKWhConsumption" not in payload


def test_parse_simulation_results_selects_cheapest_matching_contract_and_fuel():
    """Simulation parser should pick cheapest product matching contract/fuel filter."""
    simulation_data = {
        "computedComparisonData": {"energyComparison": {"uuid": "abc-123"}},
        "forwardResults": [
            {
                "total": "1600.00",
                "savings": "0",
                "supplier": {"name": "Supplier A"},
                "products": [
                    {
                        "productName": "A Fixed",
                        "energy": "ELEC",
                        "isFixed": True,
                        "total": "1600.00",
                        "priceGroups": [{"groupName": "Energy", "total": "800.00"}],
                    }
                ],
            },
            {
                "total": "1400.00",
                "savings": "10",
                "supplier": {"name": "Supplier B"},
                "products": [
                    {
                        "productName": "B Variable",
                        "energy": "ELEC",
                        "isFixed": False,
                        "total": "1400.00",
                        "priceGroups": [
                            {"groupName": "Energy", "total": "700.00"},
                            {"groupName": "Taxes", "total": "200.00"},
                            {"groupName": "Network costs", "total": "300.00"},
                        ],
                    }
                ],
            },
        ],
    }

    parsed_variable = _parse_simulation_results(
        simulation_data,
        ContractType.VARIABLE,
        "elektriciteit",
        3500,
        "Elektriciteit",
    )
    variable_offer = parsed_variable["Elektriciteit"][0]
    assert variable_offer["provider"] == "Supplier B"
    assert variable_offer["name"] == "B Variable"

    parsed_fixed = _parse_simulation_results(
        simulation_data,
        ContractType.FIXED,
        "elektriciteit",
        3500,
        "Elektriciteit",
    )
    fixed_offer = parsed_fixed["Elektriciteit"][0]
    assert fixed_offer["provider"] == "Supplier A"
    assert fixed_offer["name"] == "A Fixed"
