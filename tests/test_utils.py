"""Tests for MyEnergy parsing and data refresh behavior."""

import pytest
import requests
from bs4 import BeautifulSoup
import voluptuous as vol

from custom_components.myenergy.sensor import ComponentData
from custom_components.myenergy.utils import (
    ComparisonUnavailableError,
    ComponentSession,
    ContractType,
    _build_simulation_payload,
    _extract_results_page_url,
    check_settings,
    _build_section_name,
    _extract_euro_value,
    _parse_simulation_results,
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


def test_extract_results_page_url_finds_relative_link():
    """Helper should find first resultaten link and resolve relative URLs."""
    html = '<a href="/resultaten/abc-123">Bekijk resultaten</a>'
    assert (
        _extract_results_page_url(html, "https://www.mijnenergie.be/vergelijking/stap-2/xyz")
        == "https://www.mijnenergie.be/resultaten/abc-123"
    )


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


def test_manual_results_url_follows_linked_results_page():
    """Step-like manual page should follow embedded resultaten URL before fallback."""
    config = {
        "manual_results_url": "https://example.com/manual-step",
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
        def __init__(self, text, status_code=200, url=""):
            self.text = text
            self.status_code = status_code
            self.url = url

        def raise_for_status(self):
            return None

    class _FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout=30, allow_redirects=True):
            self.calls.append(url)
            if url == "https://example.com/manual-step":
                return _Response(
                    '<html><body><a href="https://example.com/resultaten/abc">Open</a></body></html>',
                    url=url,
                )

            if url == "https://example.com/resultaten/abc":
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
                    """,
                    url=url,
                )

            return _Response("", url=url)

    component_session = ComponentSession()
    component_session.s = _FakeSession()

    result = component_session.get_data(config, ContractType.FIXED)

    assert "Elektriciteit" in result
    assert component_session.s.calls == [
        "https://example.com/manual-step",
        "https://example.com/resultaten/abc",
    ]


def test_manual_results_url_retries_after_privacy_gate_redirect():
    """When redirected to DPG consent, scraper should call callback and retry URL."""
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

    privacy_redirect_url = (
        "https://myprivacy.dpgmedia.be/consent?siteKey=x&callbackUrl="
        "https%3A%2F%2Fwww.mijnenergie.be%2Fprivacygate-confirm%3FredirectUri%3D%252Fmanual"
    )

    class _Response:
        def __init__(self, text, status_code=200, url=""):
            self.text = text
            self.status_code = status_code
            self.url = url

        def raise_for_status(self):
            return None

    class _FakeSession:
        def __init__(self):
            self.calls = []
            self._manual_count = 0

        def get(self, url, timeout=30, allow_redirects=True):
            self.calls.append(url)

            if url == "https://example.com/manual":
                self._manual_count += 1
                if self._manual_count == 1:
                    return _Response("consent", url=privacy_redirect_url)
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
                    """,
                    url=url,
                )

            if url == "https://www.mijnenergie.be/privacygate-confirm?redirectUri=%2Fmanual":
                return _Response("ok", url=url)

            return _Response("", url=url)

    component_session = ComponentSession()
    component_session.s = _FakeSession()

    result = component_session.get_data(config, ContractType.FIXED)

    assert "Elektriciteit" in result
    assert component_session.s.calls == [
        "https://example.com/manual",
        "https://www.mijnenergie.be/privacygate-confirm?redirectUri=%2Fmanual",
        "https://example.com/manual",
    ]


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

    assert payload["meterType"] == "MONO"
    assert payload["eAnnualDayConsumption"] == 3500
    assert payload["eAnnualNightConsumption"] is None
    assert payload["eAnnualDayInjection"] is None
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
