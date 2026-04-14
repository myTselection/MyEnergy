"""Tests for VtestSession parsing, form building, caching, and VtestData coordinator."""

import pytest
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

from custom_components.myenergy.sensor import VtestData, VtestSensor
from custom_components.myenergy.utils import (
    ContractType,
    FuelType,
    VtestSession,
    normalize_input_config,
)

# ---------------------------------------------------------------------------
# Fixtures / shared helpers
# ---------------------------------------------------------------------------

MAIN_PAGE_HTML = """
<html>
<body>
<form>
  <input name="__RequestVerificationToken" value="csrf-abc-123" />
  <select id="PostalCode">
    <option value=""></option>
    <option value="1001">1000 - Brussel</option>
    <option value="7654">9000 - Gent</option>
    <option value="7655">9000 - Gent (deelgemeente)</option>
    <option value="9999">9999 - Unknown</option>
  </select>
</form>
</body>
</html>
"""

RESULTS_HTML_ELEC_ONLY = """
<html><body>
  <div class="resultitem ct-ELECTRICITY" data-tarifftype="FIXED" data-price="1140,00">
    <span id="supplier-name">Engie</span>
    <h4 class="productNameStyle">Vast Comfort</h4>
  </div>
  <div class="resultitem ct-ELECTRICITY" data-tarifftype="VARIABLE" data-price="840,00">
    <span id="supplier-name">Luminus</span>
    <h4 class="productNameStyle">Variabel Flex</h4>
  </div>
</body></html>
"""

BASE_CONFIG = {
    "postalcode": "9000",
    "electricity_digital_counter": False,
    "day_electricity_consumption": 3500,
    "night_electricity_consumption": 0,
    "excl_night_electricity_consumption": 0,
    "solar_panels": False,
    "electricity_injection": 0,
    "electricity_injection_night": 0,
    "electricity_provider": "Engie",
    "inverter_power": 0,
    "combine_elec_and_gas": False,
    "gas_consumption": 0,
    "gas_provider": "No provider",
    "directdebit_invoice": True,
    "email_invoice": True,
    "online_support": True,
    "electric_car": False,
}


def _session_with_fake_http(main_page_html: str, results_html: str) -> VtestSession:
    """Return a VtestSession whose HTTP calls are intercepted."""

    class _FakeResponse:
        def __init__(self, text):
            self.text = text
            self.status_code = 200
            self.url = VtestSession.VTEST_URL

        def raise_for_status(self):
            pass

    class _FakeHttpSession:
        def __init__(self):
            self.headers = {}
            self._get_calls = 0
            self._post_calls = 0

        def update(self, d):
            self.headers.update(d)

        def get(self, url, **kwargs):
            self._get_calls += 1
            return _FakeResponse(main_page_html)

        def post(self, url, **kwargs):
            self._post_calls += 1
            return _FakeResponse(results_html)

    session = VtestSession.__new__(VtestSession)
    session._location_id_cache = {}
    session._results_cache = None
    http = _FakeHttpSession()
    session.s = http
    return session


# ---------------------------------------------------------------------------
# _extract_location_id
# ---------------------------------------------------------------------------


def test_extract_location_id_returns_first_match():
    """Should return LocationId for the first matching postalcode option."""
    session = VtestSession.__new__(VtestSession)
    result = session._extract_location_id(MAIN_PAGE_HTML, "9000")
    assert result == "7654"


def test_extract_location_id_returns_none_for_unknown_postalcode():
    """Should return None when no option matches the postalcode."""
    session = VtestSession.__new__(VtestSession)
    result = session._extract_location_id(MAIN_PAGE_HTML, "4444")
    assert result is None


def test_extract_location_id_returns_none_when_select_missing():
    """Should return None when the PostalCode select is absent from the page."""
    session = VtestSession.__new__(VtestSession)
    result = session._extract_location_id("<html><body></body></html>", "9000")
    assert result is None


def test_extract_location_id_brussel():
    """Should correctly resolve Brussels postal code."""
    session = VtestSession.__new__(VtestSession)
    result = session._extract_location_id(MAIN_PAGE_HTML, "1000")
    assert result == "1001"


# ---------------------------------------------------------------------------
# _extract_csrf_token
# ---------------------------------------------------------------------------


def test_extract_csrf_token_returns_value():
    """Should extract the CSRF token from the hidden input field."""
    session = VtestSession.__new__(VtestSession)
    token = session._extract_csrf_token(MAIN_PAGE_HTML)
    assert token == "csrf-abc-123"


def test_extract_csrf_token_returns_empty_when_missing():
    """Should return empty string when no CSRF input is present."""
    session = VtestSession.__new__(VtestSession)
    token = session._extract_csrf_token("<html><body></body></html>")
    assert token == ""


# ---------------------------------------------------------------------------
# _build_form_data
# ---------------------------------------------------------------------------


def _form_last(tuples, name):
    """Return the last value for *name* in the tuple list, or None if absent."""
    vals = [v for n, v in tuples if n == name]
    return vals[-1] if vals else None


def _form_has(tuples, name, value=None):
    """Return True if *name* appears in tuples (optionally matching *value*)."""
    return any(n == name and (value is None or v == value) for n, v in tuples)


def test_build_form_data_electricity_only():
    """Electricity-only config should include electricity fields and omit gas."""
    session = VtestSession.__new__(VtestSession)
    parsed = normalize_input_config(BASE_CONFIG)
    form = session._build_form_data(MAIN_PAGE_HTML, parsed, "7654")

    assert _form_has(form, "EnergyTypeElectricity", "true")
    assert not _form_has(form, "EnergyTypeGas")
    assert _form_last(form, "UsageDay") == "3500"
    assert _form_last(form, "HasDigitalMeter") == "false"
    assert _form_last(form, "HasNightMeter") == "false"
    assert _form_has(form, "LocationId", "7654")
    assert _form_has(form, "PostalCode", "7654")
    assert _form_has(form, "__RequestVerificationToken", "csrf-abc-123")
    assert _form_last(form, "UserConsumption") == "2"


def test_build_form_data_gas_only():
    """Gas-only config should include gas fields and omit electricity."""
    config = {**BASE_CONFIG, "day_electricity_consumption": 0, "gas_consumption": 15000}
    session = VtestSession.__new__(VtestSession)
    parsed = normalize_input_config(config)
    form = session._build_form_data(MAIN_PAGE_HTML, parsed, "7654")

    assert _form_has(form, "EnergyTypeGas", "true")
    assert not _form_has(form, "EnergyTypeElectricity")
    assert _form_last(form, "UsageGas") == "15000"
    assert _form_last(form, "GasMeterUnit") == "1"


def test_build_form_data_night_meter():
    """Night meter consumption should set HasNightMeter=true and include UsageNight."""
    config = {**BASE_CONFIG, "day_electricity_consumption": 2000, "night_electricity_consumption": 1000}
    session = VtestSession.__new__(VtestSession)
    parsed = normalize_input_config(config)
    form = session._build_form_data(MAIN_PAGE_HTML, parsed, "7654")

    assert _form_last(form, "HasNightMeter") == "true"
    assert _form_last(form, "UsageNight") == "1000"
    assert not _form_has(form, "HasExclusiveNight", "true")


def test_build_form_data_exclusive_night():
    """Exclusive night meter should set HasExclusiveNight=true and include UsageExclusiveNight."""
    config = {**BASE_CONFIG, "excl_night_electricity_consumption": 500}
    session = VtestSession.__new__(VtestSession)
    parsed = normalize_input_config(config)
    form = session._build_form_data(MAIN_PAGE_HTML, parsed, "7654")

    assert _form_has(form, "HasExclusiveNight", "true")
    assert _form_last(form, "UsageExclusiveNight") == "500"


def test_build_form_data_solar_panels_with_inverter():
    """Solar config should include HasSolarPanels, InjectionDay, and InverterPower in kW."""
    config = {
        **BASE_CONFIG,
        "solar_panels": True,
        "electricity_injection": 1200,
        "inverter_power": 3.5,  # kW (as entered by user) → should become "3,50"
    }
    session = VtestSession.__new__(VtestSession)
    parsed = normalize_input_config(config)
    form = session._build_form_data(MAIN_PAGE_HTML, parsed, "7654")

    assert _form_has(form, "HasSolarPanels", "true")
    assert _form_last(form, "InjectionDay") == "1200"
    assert _form_has(form, "KnowsInverterPower", "true")
    assert _form_last(form, "InverterPower") == "3,50"


def test_build_form_data_digital_meter():
    """Digital meter flag should map to HasDigitalMeter=true."""
    config = {**BASE_CONFIG, "electricity_digital_counter": True}
    session = VtestSession.__new__(VtestSession)
    parsed = normalize_input_config(config)
    form = session._build_form_data(MAIN_PAGE_HTML, parsed, "7654")

    assert _form_last(form, "HasDigitalMeter") == "true"


# ---------------------------------------------------------------------------
# _parse_all_results
# ---------------------------------------------------------------------------


def _make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_parse_all_results_finds_fixed_and_variable_electricity():
    """Both FIXED and VARIABLE electricity results should be parsed from .resultitem cards."""
    session = VtestSession.__new__(VtestSession)
    session.VTEST_URL = VtestSession.VTEST_URL
    parsed_config = normalize_input_config(BASE_CONFIG)
    soup = _make_soup(RESULTS_HTML_ELEC_ONLY)

    all_results = session._parse_all_results(soup, parsed_config)

    fixed = all_results.get(ContractType.FIXED.code, {})
    variable = all_results.get(ContractType.VARIABLE.code, {})

    assert FuelType.ELECTRICITY.fullnameNL in fixed
    assert FuelType.ELECTRICITY.fullnameNL in variable

    fixed_card = fixed[FuelType.ELECTRICITY.fullnameNL][0]
    variable_card = variable[FuelType.ELECTRICITY.fullnameNL][0]

    # Fixed is cheapest fixed → Engie (1140 €/jaar)
    assert fixed_card["provider"] == "Engie"
    assert fixed_card["name"] == "Vast Comfort"

    # Variable is cheapest variable → Luminus (840 €/jaar)
    assert variable_card["provider"] == "Luminus"
    assert variable_card["name"] == "Variabel Flex"


def test_parse_all_results_computes_cents_per_kwh():
    """Annual cost card should include c€/kWh computed from yearly consumption."""
    session = VtestSession.__new__(VtestSession)
    session.VTEST_URL = VtestSession.VTEST_URL
    parsed_config = normalize_input_config(BASE_CONFIG)
    soup = _make_soup(RESULTS_HTML_ELEC_ONLY)

    all_results = session._parse_all_results(soup, parsed_config)
    card = all_results[ContractType.FIXED.code][FuelType.ELECTRICITY.fullnameNL][0]

    price_info = card["Jaarlijkse kostprijs"]
    assert len(price_info) == 3
    # 1140 / 3500 * 100 ≈ 32.57 c€/kWh
    assert "c€/kWh" in price_info[0]
    assert "3500 kWh/jaar" in price_info[1]
    assert "€ 1140.00/jaar" in price_info[2]


def test_parse_all_results_empty_html_returns_empty_dicts():
    """Empty HTML should produce empty dicts for all contract types."""
    session = VtestSession.__new__(VtestSession)
    session.VTEST_URL = VtestSession.VTEST_URL
    parsed_config = normalize_input_config(BASE_CONFIG)
    soup = _make_soup("<html><body></body></html>")

    all_results = session._parse_all_results(soup, parsed_config)

    for ct in ContractType:
        assert all_results.get(ct.code, {}) == {}


def test_parse_all_results_selects_cheapest_card():
    """When multiple cards of the same type exist, the cheapest annual cost wins."""
    html = """
    <html><body>
      <div class="resultitem ct-ELECTRICITY" data-tarifftype="FIXED" data-price="2000,00">
        <span id="supplier-name">Expensive</span>
        <h4 class="productNameStyle">Vast Duur</h4>
      </div>
      <div class="resultitem ct-ELECTRICITY" data-tarifftype="FIXED" data-price="900,00">
        <span id="supplier-name">Cheap</span>
        <h4 class="productNameStyle">Vast Goedkoop</h4>
      </div>
    </body></html>
    """
    session = VtestSession.__new__(VtestSession)
    session.VTEST_URL = VtestSession.VTEST_URL
    parsed_config = normalize_input_config(BASE_CONFIG)
    soup = _make_soup(html)

    all_results = session._parse_all_results(soup, parsed_config)
    fixed = all_results[ContractType.FIXED.code]
    assert fixed[FuelType.ELECTRICITY.fullnameNL][0]["provider"] == "Cheap"


def test_parse_all_results_gas_only_config():
    """Gas-only config should only produce gas results, not electricity."""
    html = """
    <html><body>
      <div class="resultitem ct-GAS" data-tarifftype="FIXED" data-price="1500,00">
        <span id="supplier-name">Engie</span>
        <h4 class="productNameStyle">Gas Vast Plan</h4>
      </div>
    </body></html>
    """
    config = {**BASE_CONFIG, "day_electricity_consumption": 0, "gas_consumption": 15000}
    session = VtestSession.__new__(VtestSession)
    session.VTEST_URL = VtestSession.VTEST_URL
    parsed_config = normalize_input_config(config)
    soup = _make_soup(html)

    all_results = session._parse_all_results(soup, parsed_config)
    fixed = all_results[ContractType.FIXED.code]

    assert FuelType.GAS.fullnameNL in fixed
    assert FuelType.ELECTRICITY.fullnameNL not in fixed


# ---------------------------------------------------------------------------
# get_data - caching
# ---------------------------------------------------------------------------


def test_get_data_returns_results_and_populates_cache():
    """get_data should POST to vtest.be and return parsed results."""
    session = _session_with_fake_http(MAIN_PAGE_HTML, RESULTS_HTML_ELEC_ONLY)
    result = session.get_data(BASE_CONFIG, ContractType.FIXED)

    assert isinstance(result, dict)
    assert FuelType.ELECTRICITY.fullnameNL in result
    assert session.s._post_calls == 1


def test_get_data_uses_cache_on_second_call():
    """Second call with same config should use cache and skip the POST."""
    session = _session_with_fake_http(MAIN_PAGE_HTML, RESULTS_HTML_ELEC_ONLY)

    session.get_data(BASE_CONFIG, ContractType.FIXED)
    post_calls_after_first = session.s._post_calls

    session.get_data(BASE_CONFIG, ContractType.VARIABLE)
    assert session.s._post_calls == post_calls_after_first  # no extra POST


def test_get_data_bypasses_cache_when_expired():
    """Expired cache should trigger a new POST."""
    session = _session_with_fake_http(MAIN_PAGE_HTML, RESULTS_HTML_ELEC_ONLY)

    session.get_data(BASE_CONFIG, ContractType.FIXED)
    assert session.s._post_calls == 1

    # Manually expire the cache
    old_key, _, old_data = session._results_cache
    session._results_cache = (old_key, datetime.now() - timedelta(hours=2), old_data)

    session.get_data(BASE_CONFIG, ContractType.FIXED)
    assert session.s._post_calls == 2


def test_get_data_returns_empty_when_location_id_not_found():
    """Missing LocationId in the page select should cause get_data to return {}."""
    html_no_postalcode = "<html><body><input name='__RequestVerificationToken' value='x'/></body></html>"
    session = _session_with_fake_http(html_no_postalcode, RESULTS_HTML_ELEC_ONLY)
    result = session.get_data(BASE_CONFIG, ContractType.FIXED)

    assert result == {}
    # No POST should have been made since LocationId lookup failed
    assert session.s._post_calls == 0


def test_get_data_location_id_cached_avoids_repeated_extraction():
    """Once a LocationId is resolved, subsequent calls should reuse the cached value."""
    session = _session_with_fake_http(MAIN_PAGE_HTML, RESULTS_HTML_ELEC_ONLY)

    # Warm up with first call
    session.get_data(BASE_CONFIG, ContractType.FIXED)
    assert "9000" in session._location_id_cache

    # Replace _extract_location_id with a sentinel that would fail if called
    extraction_calls = {"n": 0}

    def _should_not_extract(html, postalcode):
        extraction_calls["n"] += 1
        raise AssertionError("_extract_location_id should not be called again")

    session._extract_location_id = _should_not_extract

    # Expire the results cache so a full round-trip is attempted (GET + POST),
    # but _extract_location_id must NOT be called since location_id is cached.
    old_key, _, old_data = session._results_cache
    session._results_cache = (old_key, datetime.now() - timedelta(hours=2), old_data)

    result = session.get_data(BASE_CONFIG, ContractType.FIXED)

    assert isinstance(result, dict)
    assert extraction_calls["n"] == 0
    assert "9000" in session._location_id_cache


# ---------------------------------------------------------------------------
# VtestData coordinator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vtest_data_forced_update_stores_contract_keys(hass):
    """_forced_update should store F and V keys even when session returns empty."""
    config = {**BASE_CONFIG}
    data = VtestData(config, hass)

    def _empty_get_data(cfg, ct):
        return {}

    data._session.get_data = _empty_get_data

    await data._forced_update()

    assert ContractType.FIXED.code in data._details
    assert ContractType.VARIABLE.code in data._details
    assert data._refresh_required is True


@pytest.mark.asyncio
async def test_vtest_data_forced_update_clears_retry_on_success(hass):
    """_forced_update should reset _refresh_retry and _refresh_required on success."""
    config = {**BASE_CONFIG}
    data = VtestData(config, hass)
    data._refresh_retry = 3

    fixed_result = {FuelType.ELECTRICITY.fullnameNL: [{"name": "X", "provider": "Y", "Jaarlijkse kostprijs": ["30,00 c€/kWh", "3500 kWh/jaar", "€ 1050.00/jaar"]}]}
    variable_result = {FuelType.ELECTRICITY.fullnameNL: [{"name": "Z", "provider": "W", "Jaarlijkse kostprijs": ["28,00 c€/kWh", "3500 kWh/jaar", "€ 980.00/jaar"]}]}

    call_count = {"n": 0}

    def _good_get_data(cfg, ct):
        call_count["n"] += 1
        return fixed_result if ct == ContractType.FIXED else variable_result

    data._session.get_data = _good_get_data

    await data._forced_update()

    assert data._refresh_retry == 0
    assert data._refresh_required is False


@pytest.mark.asyncio
async def test_vtest_data_forced_update_handles_exception(hass):
    """_forced_update should not raise when session.get_data throws."""
    config = {**BASE_CONFIG}
    data = VtestData(config, hass)

    def _failing_get_data(cfg, ct):
        raise RuntimeError("network error")

    data._session.get_data = _failing_get_data

    # Should not raise
    await data._forced_update()

    assert data._refresh_required is True


# ---------------------------------------------------------------------------
# VtestSensor state & attributes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vtest_sensor_state_computed_from_price_info(hass):
    """Sensor state should be the c€/kWh value as a float (converted to €/kWh)."""
    config = {**BASE_CONFIG}
    data = VtestData(config, hass)
    data._details = {
        ContractType.FIXED.code: {
            FuelType.ELECTRICITY.fullnameNL: [
                {
                    "name": "Vast Plan",
                    "provider": "Engie",
                    "url": "https://www.vtest.be/",
                    "Jaarlijkse kostprijs": ["32,57 c€/kWh", "3500 kWh/jaar", "€ 1140.00/jaar"],
                }
            ]
        },
        ContractType.VARIABLE.code: {},
    }

    async def _noop_update():
        pass

    data.update = _noop_update

    sensor = VtestSensor(data, "9000", FuelType.ELECTRICITY, ContractType.FIXED)
    await sensor.async_update()

    assert sensor.state == pytest.approx(0.3257, rel=1e-3)
    assert sensor._providername == "Engie"
    assert sensor._contractname == "Vast Plan"
    assert sensor._priceyear == "€ 1140.00/jaar"
    assert sensor._kWhyear == "3500 kWh/jaar"


@pytest.mark.asyncio
async def test_vtest_sensor_state_none_when_no_data(hass):
    """Sensor state should be None when no data is available for the contract type."""
    config = {**BASE_CONFIG}
    data = VtestData(config, hass)
    data._details = {
        ContractType.FIXED.code: {},
        ContractType.VARIABLE.code: {},
    }

    async def _noop_update():
        pass

    data.update = _noop_update

    sensor = VtestSensor(data, "9000", FuelType.ELECTRICITY, ContractType.FIXED)
    await sensor.async_update()

    assert sensor.state is None


@pytest.mark.asyncio
async def test_vtest_sensor_attributes_contain_required_keys(hass):
    """Sensor extra_state_attributes should expose all required keys."""
    config = {**BASE_CONFIG}
    data = VtestData(config, hass)
    data._details = {
        ContractType.FIXED.code: {
            FuelType.ELECTRICITY.fullnameNL: [
                {
                    "name": "Plan X",
                    "provider": "Luminus",
                    "url": "https://www.vtest.be/",
                    "Jaarlijkse kostprijs": ["28,00 c€/kWh", "3500 kWh/jaar", "€ 980.00/jaar"],
                }
            ]
        },
        ContractType.VARIABLE.code: {},
    }

    async def _noop_update():
        pass

    data.update = _noop_update

    sensor = VtestSensor(data, "9000", FuelType.ELECTRICITY, ContractType.FIXED)
    await sensor.async_update()
    attrs = sensor.extra_state_attributes

    for key in ("postalcode", "fuel type", "contract type", "url", "provider name",
                 "contract name", "total price per year", "total kWh per year"):
        assert key in attrs, f"Missing attribute: {key}"

    assert attrs["postalcode"] == "9000"
    assert attrs["provider name"] == "Luminus"


@pytest.mark.asyncio
async def test_vtest_sensor_unique_id_and_name(hass):
    """unique_id and name should encode postalcode, fuel type, and contract type."""
    config = {**BASE_CONFIG}
    data = VtestData(config, hass)
    data._details = {}

    sensor = VtestSensor(data, "9000", FuelType.ELECTRICITY, ContractType.FIXED)

    assert "9000" in sensor.unique_id
    assert FuelType.ELECTRICITY.fullnameEN in sensor.unique_id
    assert ContractType.FIXED.fullname in sensor.unique_id
    assert sensor.name == sensor.unique_id


def test_vtest_sensor_unit_of_measurement():
    """Unit should be €/kWh."""
    config = {**BASE_CONFIG}
    data = VtestData.__new__(VtestData)
    data._config = config
    data._parsed_inputs = normalize_input_config(config)
    data._details = {}
    data._last_update = None
    data._postalcode = "9000"

    sensor = VtestSensor(data, "9000", FuelType.ELECTRICITY, ContractType.FIXED)
    assert sensor.unit_of_measurement == "€/kWh"


def test_vtest_sensor_icon_gas_vs_electricity():
    """Icon should differ for gas vs electricity."""
    config = {**BASE_CONFIG}
    data = VtestData.__new__(VtestData)
    data._config = config
    data._parsed_inputs = normalize_input_config(config)
    data._details = {}
    data._last_update = None
    data._postalcode = "9000"

    elec_sensor = VtestSensor(data, "9000", FuelType.ELECTRICITY, ContractType.FIXED)
    gas_sensor = VtestSensor(data, "9000", FuelType.GAS, ContractType.FIXED)

    assert elec_sensor.icon != gas_sensor.icon
    assert "gas" in gas_sensor.icon
