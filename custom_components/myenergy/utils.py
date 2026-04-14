
import logging
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import urllib.parse
from enum import Enum

from .const import (
    DOMAIN,
)

import voluptuous as vol

_LOGGER = logging.getLogger(DOMAIN)

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.0%z"


providers = {"No provider": "0","Social rate": "1000", "Aspiravi": "30", "Bolt": "29","Brusol": 34, "Cociter": 31, "DATS 24": "33", "Ebem": "13", "Ecopower": "14", "Elegant":"12", "Eneco": "15",
                 "Energie.be": "35", "Engie": "5", "Fluvius": "37", "Frank Energie": "41","Luminus": "9", "Mega": "21", "Octa+":  "19", "Tina":  "38", "TotalEnergies": "8", 
                 "Trevion": "3", "Wase Wind": "16", 'Wind voor "A"': "36", "Other": "1"}

headings= ["Energiekosten", "Nettarieven en heffingen", "Promo via Mijnenergie"]


class ComparisonUnavailableError(Exception):
    """Raised when MijnEnergie no longer serves comparison results for generated URL."""


def _extract_euro_value(text):
    if not text:
        return None
    match = re.search(r"€\s*([0-9\.,]+)", text)
    if not match:
        return None
    value = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def _normalize_provider_name(name):
    return name.replace("Logo ", "").strip().title() if name else ""


def _build_section_name(type_comp):
    if type_comp == "elektriciteit":
        return FuelType.ELECTRICITY.fullnameNL
    if type_comp == "aardgas":
        return FuelType.GAS.fullnameNL
    return type_comp.title()


def _parse_new_results_cards(soup, result_url, yearly_consumption, section_name):
    cards = soup.select(
        "article, div[class*='card card-energy-details'], div.card-energy-details, div.card-body"
    )
    parsed_cards = []
    seen_cards = set()

    for card in cards:
        # Avoid duplicates when both container and nested body are selected.
        if id(card) in seen_cards:
            continue
        seen_cards.add(id(card))

        if "card-body" in (card.get("class") or []) and card.find_parent(
            "div", class_=re.compile(r"card-energy-details")
        ):
            continue

        provider_img = card.select_one("img[alt]")
        provider_name = _normalize_provider_name(provider_img.get("alt", "") if provider_img else "")

        # The first heading in the card is usually the product/contract name.
        name_el = card.select_one("h2, h3, h4")
        contract_name = name_el.get_text(" ", strip=True) if name_el else ""
        if not contract_name:
            legacy_name_el = card.select_one(
                "li.list-inline-item.large-body-font-size.text-strong"
            )
            if legacy_name_el is not None:
                contract_name = legacy_name_el.get_text(" ", strip=True)

        card_text = card.get_text(" ", strip=True)
        annual_match = re.search(r"€\s*[0-9\.,]+\s*/\s*jaar", card_text, re.IGNORECASE)
        monthly_match = re.search(r"€\s*[0-9\.,]+\s*/\s*maand", card_text, re.IGNORECASE)

        annual_value = _extract_euro_value(annual_match.group(0) if annual_match else "")
        if annual_value is None:
            annual_label_match = re.search(
                r"Jaarlijkse[^€]*€\s*([0-9\.,]+)", card_text, re.IGNORECASE
            )
            if annual_label_match:
                annual_value = _extract_euro_value(f"€ {annual_label_match.group(1)}")

        if annual_value is None:
            context_patterns = [
                r"(?:jaarlijk(?:e|se)?(?:\s+kostprijs)?|annual(?:\s+cost)?|yearly(?:\s+cost)?|per\s+year|per\s+jaar|year)\D{0,40}€\s*([0-9\.,]+)",
                r"€\s*([0-9\.,]+)\D{0,20}(?:/\s*(?:jaar|year)|per\s*(?:jaar|year))",
            ]
            for pattern in context_patterns:
                context_match = re.search(pattern, card_text, re.IGNORECASE)
                if context_match:
                    annual_value = _extract_euro_value(f"€ {context_match.group(1)}")
                    if annual_value is not None:
                        break

        if annual_value is None:
            euro_candidates = []
            for euro_match in re.finditer(r"€\s*([0-9\.,]+)", card_text):
                euro_value = _extract_euro_value(euro_match.group(0))
                if euro_value is not None:
                    euro_candidates.append((euro_value, euro_match.start()))

            if euro_candidates:
                keyword_positions = [
                    keyword_match.start()
                    for keyword_match in re.finditer(
                        r"\b(?:jaarlijks?e?|per\s*jaar|jaar|annual|yearly|per\s*year|year)\b",
                        card_text,
                        re.IGNORECASE,
                    )
                ]

                if keyword_positions:
                    annual_value = min(
                        euro_candidates,
                        key=lambda candidate: min(
                            abs(candidate[1] - keyword_pos)
                            for keyword_pos in keyword_positions
                        ),
                    )[0]
                else:
                    euro_values = [value for value, _ in euro_candidates]
                    annual_value = max(euro_values)
                    _LOGGER.warning(
                        "Annual value fallback used max(euro_values). candidates=%s card_text=%s",
                        euro_values,
                        card_text[:300] if len(card_text) > 300 else card_text,
                    )

        monthly_value = _extract_euro_value(monthly_match.group(0) if monthly_match else "")

        json_data = {
            "name": contract_name,
            "url": result_url,
            "provider": provider_name,
        }

        if monthly_value is not None:
            json_data["Maandelijkse kostprijs"] = [f"€ {monthly_value:.2f}/maand"]

        if annual_value is not None:
            if yearly_consumption > 0:
                cents_per_kwh = (annual_value / yearly_consumption) * 100
                json_data["Jaarlijkse kostprijs"] = [
                    f"{cents_per_kwh:.2f}".replace(".", ",") + " c€/kWh",
                    f"{yearly_consumption} kWh/jaar",
                    f"€ {annual_value:.2f}/jaar",
                ]
            else:
                json_data["Jaarlijkse kostprijs"] = [f"€ {annual_value:.2f}/jaar"]

        if json_data.get("provider") and json_data.get("Jaarlijkse kostprijs"):
            parsed_cards.append(json_data)

    if not parsed_cards:
        return {}

    return {section_name: [parsed_cards[0]]}


def _to_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_input_config(config):
    """Normalize GUI input values so downstream payload/parsers use consistent types."""
    day_electricity_consumption = int(config.get("day_electricity_consumption", 0) or 0)
    night_electricity_consumption = int(config.get("night_electricity_consumption", 0) or 0)
    excl_night_electricity_consumption = int(config.get("excl_night_electricity_consumption", 0) or 0)
    electricity_injection = int(config.get("electricity_injection", 0) or 0)
    electricity_injection_night = int(config.get("electricity_injection_night", 0) or 0)
    gas_consumption = int(config.get("gas_consumption", 0) or 0)
    inverter_power = _to_float(config.get("inverter_power", 0.0)) or 0.0

    electricity_provider = config.get("electricity_provider", "No provider")
    gas_provider = config.get("gas_provider", "No provider")

    meter_type = "MONO" if night_electricity_consumption == 0 and excl_night_electricity_consumption == 0 else "BI"
    electricity_comp = (
        day_electricity_consumption != 0
        or night_electricity_consumption != 0
        or excl_night_electricity_consumption != 0
    )
    gas_comp = gas_consumption != 0

    elec_level = 0
    if night_electricity_consumption != 0:
        elec_level += 1
    if excl_night_electricity_consumption != 0:
        elec_level += 1

    normalized = {
        "postalcode": str(config.get("postalcode", "")),
        "electricity_digital_counter": bool(config.get("electricity_digital_counter", False)),
        "day_electricity_consumption": day_electricity_consumption,
        "night_electricity_consumption": night_electricity_consumption,
        "excl_night_electricity_consumption": excl_night_electricity_consumption,
        "solar_panels": bool(config.get("solar_panels", False)),
        "electricity_injection": electricity_injection,
        "electricity_injection_night": electricity_injection_night,
        "inverter_power": inverter_power,
        "electricity_provider": electricity_provider,
        "gas_consumption": gas_consumption,
        "gas_provider": gas_provider,
        "combine_elec_and_gas": bool(config.get("combine_elec_and_gas", False)),
        "directdebit_invoice": bool(config.get("directdebit_invoice", True)),
        "email_invoice": bool(config.get("email_invoice", True)),
        "online_support": bool(config.get("online_support", True)),
        "electric_car": bool(config.get("electric_car", False)),
        "electricity_comp": electricity_comp,
        "gas_comp": gas_comp,
        "meter_type": meter_type,
        "meter_type_api": "DUAL" if night_electricity_consumption > 0 else "MONO",
        "elec_level": elec_level,
        "electricity_provider_id": providers.get(electricity_provider, "0"),
        "gas_provider_id": providers.get(gas_provider, "0"),
    }

    return normalized


def _build_simulation_payload(config, locality):
    parsed = normalize_input_config(config)
    day_electricity_consumption = parsed["day_electricity_consumption"]
    night_electricity_consumption = parsed["night_electricity_consumption"]
    excl_night_electricity_consumption = parsed["excl_night_electricity_consumption"]
    electricity_injection = parsed["electricity_injection"]
    electricity_injection_night = parsed["electricity_injection_night"]
    gas_consumption = parsed["gas_consumption"]

    electricity_comp = parsed["electricity_comp"]
    gas_comp = parsed["gas_comp"]

    meter_type = parsed["meter_type"]
    meter_type_api = parsed["meter_type_api"]
    solar_panels = parsed["solar_panels"]

    payload = {
        "site": "www.mijnenergie.be",
        "locale": "NL",
        "clientType": "INDIV",
        "localityId": locality.get("id"),
        "localityZipCode": int(locality.get("zipCode")),
        "electricity": electricity_comp,
        "gas": gas_comp,
        "rateType": "ALL",
        "contractDuration": "ALL",
        "comparisonMethod": "VREG",
        "showPromo": True,
        "onlyGreenEnergy": False,
        "onlyElectricalVehicle": False,
        "fillingOption": "manual",
        "meterType": meter_type_api,
        "exclusiveNightMeter": excl_night_electricity_consumption > 0,
        "digitalMeter": parsed["electricity_digital_counter"],
        "solarPanels": solar_panels,
        "electricVehicle": parsed["electric_car"],
    }

    if electricity_comp:
        payload["eAnnualDayConsumption"] = int(day_electricity_consumption)
        if meter_type == "BI":
            payload["eAnnualNightConsumption"] = int(night_electricity_consumption)
        if excl_night_electricity_consumption > 0:
            payload["eAnnualExclusiveNightConsumption"] = int(excl_night_electricity_consumption)
        if solar_panels:
            payload["eAnnualDayInjection"] = int(electricity_injection)
            if meter_type == "BI":
                payload["eAnnualNightInjection"] = int(electricity_injection_night)
            payload["eInverterPower"] = parsed["inverter_power"]

    if gas_comp:
        payload["gAnnualKWhConsumption"] = int(gas_consumption)

    return payload


def _parse_simulation_results(simulation_data, contract_type, type_comp, yearly_consumption, section_name):
    result_sets = simulation_data.get("forwardResults") or simulation_data.get("results") or []
    if not result_sets:
        return {}

    expected_energy = "ELEC" if type_comp == "elektriciteit" else "GAS"
    require_fixed = contract_type.code == "F"

    best_match = None
    best_total = None

    for result in result_sets:
        supplier = result.get("supplier") or {}
        for product in result.get("products") or []:
            is_fixed = bool(product.get("isFixed"))
            if require_fixed != is_fixed:
                continue

            energy = (product.get("energy") or "").upper()
            if energy not in (expected_energy, "DUAL"):
                continue

            total = _to_float(product.get("total"), _to_float(result.get("total"), 0.0))
            if total <= 0:
                continue

            if best_total is None or total < best_total:
                best_total = total
                best_match = (result, product, supplier)

    if best_match is None:
        return {}

    result, product, supplier = best_match
    annual_total = _to_float(product.get("total"), _to_float(result.get("total"), 0.0))
    monthly_total = annual_total / 12 if annual_total > 0 else 0

    price_groups = product.get("priceGroups") or []
    energy_cost = ""
    net_and_taxes = 0.0
    for group in price_groups:
        group_name = (group.get("groupName") or "").lower()
        group_total = _to_float(group.get("total"), 0.0)
        if "energy" in group_name:
            energy_cost = f"€ {group_total:.2f}/jaar"
        if "network" in group_name or "tax" in group_name:
            net_and_taxes += group_total

    promo = _to_float(result.get("savings"), 0.0)

    comparison_uuid = (((simulation_data.get("computedComparisonData") or {}).get("energyComparison") or {}).get("uuid"))
    result_url = f"https://www.mijnenergie.be/vergelijking/stap-3/{comparison_uuid}" if comparison_uuid else ""

    json_data = {
        "name": product.get("productName", ""),
        "url": result_url,
        "provider": supplier.get("name", ""),
        "Maandelijkse kostprijs": [f"€ {monthly_total:.2f}/maand"],
    }

    if energy_cost:
        json_data[headings[0]] = energy_cost
    if net_and_taxes > 0:
        json_data[headings[1]] = f"€ {net_and_taxes:.2f}/jaar"
    if promo > 0:
        json_data[headings[2]] = f"€ {promo:.2f}"

    if yearly_consumption > 0:
        cents_per_kwh = (annual_total / yearly_consumption) * 100
        cents_per_kwh_text = f"{cents_per_kwh:.2f}".replace(".", ",")
        json_data["Jaarlijkse kostprijs"] = [
            f"{cents_per_kwh_text} c€/kWh",
            f"{yearly_consumption} kWh/jaar",
            f"€ {annual_total:.2f}/jaar",
        ]
    else:
        json_data["Jaarlijkse kostprijs"] = [f"€ {annual_total:.2f}/jaar"]

    return {section_name: [json_data]}


def _extract_results_page_url(html_text, source_url):
    """Extract first plausible resultaten URL from page HTML."""
    if not html_text:
        return ""

    patterns = [
        r'href=["\']([^"\']*(?:/resultaten/|/energie-vergelijken-3-resultaten-|/vergelijking/stap-3/)[^"\']*)["\']',
        r'"(https://www\.mijnenergie\.be/(?:resultaten/|energie-vergelijken-3-resultaten-|vergelijking/stap-3/)[^"]+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            return urllib.parse.urljoin(source_url, match.group(1))

    return ""

class FuelType(Enum):
    GAS = ("G","Aardgas","Gas")
    ELECTRICITY = ("E","Elektriciteit","Electricity")
    COMBINED = ("C","Elektriciteit en aardgas","Electricity and Gas")
    
    def __init__(self, code,fullnameNL, fullnameEN):
        self.code = code
        self.fullnameNL = fullnameNL
        self.fullnameEN = fullnameEN

class ContractType(Enum):
    FIXED = ("F","Fixed")
    VARIABLE = ("V","Variable")
    
    def __init__(self, code,fullname):
        self.code = code
        self.fullname = fullname

def check_settings(config, hass):
    if not any(config.get(i) for i in ["postalcode"]):
        _LOGGER.error("postalcode was not set")
        raise vol.Invalid("Missing settings to setup the sensor.")
    return True
        

class VtestSession(object):
    """Fetches energy comparison data from vtest.be (VREG official Belgian tool)."""

    VTEST_URL = "https://www.vtest.be/"
    CACHE_TTL = timedelta(minutes=30)

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "nl-BE,nl;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Origin": "https://www.vtest.be",
                "Referer": "https://www.vtest.be/",
            }
        )
        self._location_id_cache: dict = {}
        # (cache_key, timestamp, {contract_code: parsed_results})
        self._results_cache: tuple | None = None

    def _fetch_main_page(self) -> str:
        resp = self.s.get(self.VTEST_URL, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def _extract_location_id(self, html: str, postalcode: str) -> str | None:
        """Return the LocationId value for the first matching postalcode entry."""
        soup = BeautifulSoup(html, "html.parser")
        select = soup.find("select", {"id": "PostalCode"})
        if not select:
            _LOGGER.warning("VTest: PostalCode select not found in page HTML")
            return None
        postalcode_str = str(postalcode).strip()
        for option in select.find_all("option"):
            val = option.get("value", "").strip()
            if not val:
                continue
            text = option.get_text(strip=True)
            # Option text format: "9000 - Gent"
            if text.startswith(postalcode_str + " - ") or text.startswith(postalcode_str + "-"):
                return val
        _LOGGER.warning("VTest: No LocationId found for postalcode %s", postalcode)
        return None

    def _extract_csrf_token(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        token_el = soup.find("input", {"name": "__RequestVerificationToken"})
        return token_el.get("value", "") if token_el else ""

    def _build_form_data(self, html: str, parsed: dict, location_id: str) -> list:
        """Return list of (name, value) tuples for the vtest.be form POST.

        Extracts all HTML form inputs first (preserving ASP.NET checkbox+hidden bool pairs),
        then appends our overrides. The tuple list approach is required because ASP.NET model
        binding for booleans inspects the first "true" value; dict collapses duplicate keys.
        """
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form")
        tuples: list = []
        if form:
            for inp in form.find_all("input"):
                name = inp.get("name")
                if name:
                    tuples.append((name, inp.get("value", "")))

        # Append overrides; these come after existing values and take effect for ASP.NET binding
        tuples.append(("PostalCode", location_id))
        tuples.append(("LocationId", location_id))
        tuples.append(("UserConsumption", "2"))  # "Ik ken mijn verbruik"

        if parsed["electricity_comp"]:
            tuples.append(("EnergyTypeElectricity", "true"))
            tuples.append(("UsageDay", str(parsed["day_electricity_consumption"])))
            has_night = parsed["night_electricity_consumption"] > 0
            has_excl_night = parsed["excl_night_electricity_consumption"] > 0
            tuples.append(("HasNightMeter", "true" if has_night else "false"))
            if has_night:
                tuples.append(("UsageNight", str(parsed["night_electricity_consumption"])))
            if has_excl_night:
                tuples.append(("HasExclusiveNight", "true"))
                tuples.append(("UsageExclusiveNight", str(parsed["excl_night_electricity_consumption"])))
            tuples.append(("HasDigitalMeter", "true" if parsed["electricity_digital_counter"] else "false"))
            if parsed["solar_panels"]:
                tuples.append(("HasSolarPanels", "true"))
                if parsed["electricity_injection"] > 0:
                    tuples.append(("InjectionDay", str(parsed["electricity_injection"])))
                if parsed["electricity_injection_night"] > 0:
                    tuples.append(("InjectionNight", str(parsed["electricity_injection_night"])))
                if parsed["inverter_power"] > 0:
                    tuples.append(("KnowsInverterPower", "true"))
                    # inverter_power is already in kW (user enters e.g. 3.5); vtest.be uses comma decimal
                    tuples.append(("InverterPower", f"{parsed['inverter_power']:.2f}".replace(".", ",")))

        if parsed["gas_comp"]:
            tuples.append(("EnergyTypeGas", "true"))
            tuples.append(("UsageGas", str(parsed["gas_consumption"])))
            tuples.append(("GasMeterUnit", "1"))  # kWh

        return tuples

    def _parse_all_results(self, soup: BeautifulSoup, parsed_config: dict) -> dict:
        """Return {contract_code: {section_name: [best_match]}} for all contract types.

        vtest.be result cards use .resultitem divs with CSS classes ct-ELECTRICITY / ct-GAS
        and a data-tarifftype attribute ("FIXED" or "VARIABLE"). The annual price in € is
        stored in the data-price attribute (European comma-decimal format).
        """
        electricity_comp = parsed_config["electricity_comp"]
        gas_comp = parsed_config["gas_comp"]
        day_cons = parsed_config["day_electricity_consumption"]
        night_cons = parsed_config["night_electricity_consumption"]
        excl_night_cons = parsed_config["excl_night_electricity_consumption"]
        gas_cons = parsed_config["gas_consumption"]
        yearly_elec = day_cons + night_cons + excl_night_cons

        _LOGGER.debug(
            "VTest: Total .resultitem elements: %d",
            len(soup.select(".resultitem")),
        )

        FUEL_CLASS = {
            FuelType.ELECTRICITY: "ct-ELECTRICITY",
            FuelType.GAS: "ct-GAS",
        }

        def _annual_price(item) -> float:
            raw = item.get("data-price", "").replace(".", "").replace(",", ".")
            try:
                return float(raw)
            except ValueError:
                return float("inf")

        def _best_for(fuel_type: "FuelType", contract_type: "ContractType", yearly_consumption: int) -> dict:
            fuel_cls = FUEL_CLASS.get(fuel_type, "")
            tariff_attr = "FIXED" if contract_type == ContractType.FIXED else "VARIABLE"
            section_name = fuel_type.fullnameNL

            items = [
                el for el in soup.select(f".resultitem.{fuel_cls}")
                if el.get("data-tarifftype") == tariff_attr
            ]
            _LOGGER.debug(
                "VTest: %d .resultitem.%s[data-tarifftype=%s] found",
                len(items), fuel_cls, tariff_attr,
            )

            if not items:
                _LOGGER.debug(
                    "VTest: No %s %s contract found in results",
                    fuel_type.fullnameEN,
                    contract_type.fullname,
                )
                return {}

            best = min(items, key=_annual_price)
            annual_price = _annual_price(best)

            provider_el = best.find("span", {"id": "supplier-name"})
            provider_name = _normalize_provider_name(
                provider_el.get_text(strip=True) if provider_el else ""
            )
            contract_el = best.find("h4", class_="productNameStyle")
            contract_name = contract_el.get_text(" ", strip=True) if contract_el else ""

            json_data: dict = {
                "name": contract_name,
                "url": self.VTEST_URL,
                "provider": provider_name,
            }

            if yearly_consumption > 0 and annual_price < float("inf"):
                cents_per_kwh = (annual_price / yearly_consumption) * 100
                json_data["Jaarlijkse kostprijs"] = [
                    f"{cents_per_kwh:.2f}".replace(".", ",") + " c€/kWh",
                    f"{yearly_consumption} kWh/jaar",
                    f"€ {annual_price:.2f}/jaar",
                ]
            elif annual_price < float("inf"):
                json_data["Jaarlijkse kostprijs"] = [f"€ {annual_price:.2f}/jaar"]

            return {section_name: [json_data]}

        all_results: dict = {}
        for ct in ContractType:
            ct_result: dict = {}
            if electricity_comp:
                ct_result.update(_best_for(FuelType.ELECTRICITY, ct, yearly_elec))
            if gas_comp:
                ct_result.update(_best_for(FuelType.GAS, ct, gas_cons))
            all_results[ct.code] = ct_result

        return all_results

    def get_data(self, config: dict, contract_type: "ContractType") -> dict:
        """Fetch vtest.be results and return parsed data for the requested contract type."""
        parsed = normalize_input_config(config)
        postalcode = parsed["postalcode"]

        cache_key = (
            f"{postalcode}"
            f"_{parsed['electricity_comp']}"
            f"_{parsed['gas_comp']}"
            f"_{parsed['day_electricity_consumption']}"
            f"_{parsed['night_electricity_consumption']}"
            f"_{parsed['excl_night_electricity_consumption']}"
            f"_{parsed['gas_consumption']}"
            f"_{parsed['electricity_digital_counter']}"
            f"_{parsed['solar_panels']}"
            f"_{parsed['electricity_injection']}"
            f"_{parsed['electricity_injection_night']}"
            f"_{parsed['inverter_power']}"
        )
        now = datetime.now()

        if (
            self._results_cache is not None
            and self._results_cache[0] == cache_key
            and (now - self._results_cache[1]) < self.CACHE_TTL
        ):
            _LOGGER.debug("VTest: Using cached results for %s", cache_key)
            return self._results_cache[2].get(contract_type.code, {})

        # Fetch main page for CSRF token and LocationId
        _LOGGER.debug("VTest: Fetching main page for postal code %s", postalcode)
        html = self._fetch_main_page()

        location_id = self._location_id_cache.get(postalcode)
        if location_id is None:
            location_id = self._extract_location_id(html, postalcode)
            if location_id:
                self._location_id_cache[postalcode] = location_id
            else:
                _LOGGER.warning("VTest: Cannot resolve LocationId for postal code %s", postalcode)
                return {}

        csrf_token = self._extract_csrf_token(html)
        form_tuples = self._build_form_data(html, parsed, location_id)

        _LOGGER.debug(
            "VTest: Submitting form for postal code %s (location_id=%s)", postalcode, location_id
        )
        try:
            response = self.s.post(
                self.VTEST_URL,
                data=form_tuples,
                timeout=60,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            _LOGGER.warning("VTest: HTTP error submitting form: %s", str(e))
            return {}
        _LOGGER.debug("VTest: Response status %s, url=%s", response.status_code, response.url)

        soup = BeautifulSoup(response.text, "html.parser")
        all_results = self._parse_all_results(soup, parsed)

        self._results_cache = (cache_key, now, all_results)
        _LOGGER.debug("VTest: Parsed and cached results for %s", cache_key)

        return all_results.get(contract_type.code, {})


class ComponentSession(object):
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Python/3"
        self.s.headers["Accept-Language"] = "en-US,en;q=0.9"

    def _mijnenergie_get(self, url, timeout=30):
        """Fetch MijnEnergie page and retry once after DPG privacy gate redirect."""
        response = self.s.get(url, timeout=timeout, allow_redirects=True)
        final_url = getattr(response, "url", url) or url

        if "myprivacy.dpgmedia.be/consent" not in final_url:
            return response

        parsed = urllib.parse.urlparse(final_url)
        callback_url = urllib.parse.parse_qs(parsed.query).get("callbackUrl", [""])[0]
        if callback_url:
            cb_parsed = urllib.parse.urlparse(callback_url)
            allowed_domains = ("mijnenergie.be", "dpgmedia.be", "comparateur.be")
            cb_host = (cb_parsed.hostname or "").lower()
            scheme_ok = cb_parsed.scheme in ("https", "http")
            host_ok = any(cb_host == d or cb_host.endswith("." + d) for d in allowed_domains)
            if scheme_ok and host_ok:
                try:
                    self.s.get(callback_url, timeout=timeout, allow_redirects=True)
                except requests.RequestException:
                    _LOGGER.debug("Privacy gate callback request failed for %s", url, exc_info=True)
            else:
                _LOGGER.warning("Skipping privacy gate callback with untrusted URL: %s", cb_parsed.hostname)

        return self.s.get(url, timeout=timeout, allow_redirects=True)

    def get_data(self, config, contract_type: ContractType):
        parsed = normalize_input_config(config)
        postalcode = parsed["postalcode"]
        electricity_digital_counter_n = 1 if parsed["electricity_digital_counter"] else 0
        day_electricity_consumption = parsed["day_electricity_consumption"]
        night_electricity_consumption = parsed["night_electricity_consumption"]
        excl_night_electricity_consumption = parsed["excl_night_electricity_consumption"]

        solar_panels_n = 1 if parsed["solar_panels"] else 0
        electricity_injection = parsed["electricity_injection"]
        electricity_injection_night = parsed["electricity_injection_night"]

        electricity_provider_n = parsed["electricity_provider_id"]

        inverter_power = str(parsed["inverter_power"]).replace(',', '%2C').replace('.', '%2C')

        combine_elec_and_gas_n = 1 if parsed["combine_elec_and_gas"] else 0

        gas_consumption = parsed["gas_consumption"]
        gas_provider_n = parsed["gas_provider_id"]

        directdebit_invoice_n = 1 if parsed["directdebit_invoice"] else 0
        email_invoice_n = 1 if parsed["email_invoice"] else 0
        online_support_n = 1 if parsed["online_support"] else 0
        electric_car_n = 1 if parsed["electric_car"] else 0

        electricity_comp = parsed["electricity_comp"]
        gas_comp = parsed["gas_comp"]

        types_comp = []
        if electricity_comp: 
            types_comp.append("elektriciteit")
        if gas_comp:
            types_comp.append("aardgas")
    
        elec_level = parsed["elec_level"]

        result = {}

        simulation_data = None
        locality = None
        try:
            locality_response = self.s.get(
                f"https://api.comparateur.be/zone/localities?zipCode={postalcode}",
                timeout=30,
                allow_redirects=True,
            )
            locality_response.raise_for_status()
            localities = locality_response.json() or []
            for candidate in localities:
                if str(candidate.get("zipCode")) == str(postalcode):
                    locality = candidate
                    break
            if locality is None and localities:
                locality = localities[0]
        except requests.RequestException as err:
            _LOGGER.warning(
                "Locality lookup failed, skipping simulation API and falling back to HTML parsing. error=%s",
                err,
            )

        if locality is not None:
            simulation_payload = _build_simulation_payload(config, locality)
            simulation_url = "https://api.comparateur.be/energy/comparison/simulation"
            try:
                simulation_response = self.s.post(
                    simulation_url,
                    json=simulation_payload,
                    timeout=30,
                    allow_redirects=True,
                )
                simulation_response.raise_for_status()
                simulation_data = simulation_response.json()
            except requests.RequestException as err:
                _LOGGER.warning(
                    "Simulation API call failed, falling back to HTML parsing. error=%s",
                    err,
                )
                simulation_data = None

        for type_comp in types_comp:
            section_name = _build_section_name(type_comp)
            yearly_consumption = day_electricity_consumption + night_electricity_consumption + excl_night_electricity_consumption if type_comp == "elektriciteit" else gas_consumption

            if simulation_data is not None:
                parsed = _parse_simulation_results(
                    simulation_data,
                    contract_type,
                    type_comp,
                    yearly_consumption,
                    section_name,
                )
                if parsed:
                    result.update(parsed)
                else:
                    _LOGGER.debug(
                        "Simulation API returned no %s results for contract type %s",
                        type_comp,
                        contract_type.code,
                    )
                continue

            myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={type_comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection}%7C{electricity_injection_night}%7C{solar_panels_n}%7C%7C0%21{contract_type.code}%21A%21n%7C0%21{contract_type.code}%21A%7C{combine_elec_and_gas_n}%7C{inverter_power}%7C%7C%7C%7C%7C%21%7C%7C{inverter_power}%7C%7C{electric_car_n}-{electricity_provider_n}%7C{gas_provider_n}-0"
            
            _LOGGER.debug(f"myenergy_url: {myenergy_url}")
            response = self._mijnenergie_get(myenergy_url, timeout=30)
            response.raise_for_status()

            if "NEXT_NOT_FOUND" in response.text or "Pagina niet gevonden" in response.text:
                raise ComparisonUnavailableError(
                    "Generated comparison URL returned not found page. "
                    "Automatic GUI mode is currently unsupported by MijnEnergie website."
                )
            
            _LOGGER.debug("get result status code: " + str(response.status_code))
            # _LOGGER.debug("get result response: " + str(response.text))
            soup = BeautifulSoup(response.text, 'html.parser')


            
            # sections = soup.find_all('div', class_='container-fluid container-fluid-custom')
            # for section in sections:
            
            section_ids = []
            # if electricity_comp:
            if type_comp == "elektriciteit":
                section_ids.append("RestultatElec")
            # if gas_comp:
            if type_comp == "aardgas":
                section_ids.append("RestultatGas")
            # if combine_elec_and_gas:
                # section_ids = ["RestultatDualFuel"]
            # section_ids.append("ScrollResult")
            for section_id in section_ids:
                _LOGGER.debug(f"section_id {section_id}")
                section =  soup.find(id=section_id)
                if section is None:
                    _LOGGER.debug("Section %s not found in page", section_id)
                    continue

                # sectionName = section.find("caption", class_="sr-only").text
                header = section.find("h3", class_="h4 text-strong")
                if header is None:
                    _LOGGER.debug("Section %s missing expected heading", section_id)
                    continue

                sectionName = header.text
                sectionName = sectionName.replace('Resultaten ','').title()
                # providerdetails = section.find_all('tr', class_='cleantable_overview_row')
                # non_ad_section = section.find_all('div', class_='card card-energy-details border border-light')
                non_ad_section = section.select('div[class*="card card-energy-details border border-light"]')
                if non_ad_section is None or len(non_ad_section) == 0:
                    providerdetails = section.find_all('div', class_='card-body')
                else:
                    providerdetails = non_ad_section
                providerdetails_array = []
                for providerdetail in providerdetails:
                    name_el = providerdetail.find('li', class_='list-inline-item large-body-font-size text-strong mb-2 mb-sm-0')
                    if name_el is None:
                        continue

                    providerdetails_name = name_el.text
                    providerdetails_name = providerdetails_name.replace('\n', '')

                    # Find the <img> element within the specified <div> by class name
                    provider_logo_container = providerdetail.find('div', class_='provider-logo-lg')
                    if provider_logo_container is None:
                        continue

                    img_element = provider_logo_container.find('img')
                    if img_element is None or not img_element.get('alt'):
                        continue

                    # Extract the 'alt' attribute, which contains the provider name
                    provider_name = img_element['alt']
                    provider_name = provider_name.replace('Logo ','').title()


                    # Find all table rows and extract the data
                    table_rows = providerdetail.find_all('tr')

                    # Create a list to store the table data
                    # table_data = []
                    json_data = {}
                    json_data['name'] = providerdetails_name
                    json_data['url'] = myenergy_url
                    json_data['provider'] = provider_name

                    heading_index = 0
                    # Loop through the rows and extract the data into a dictionary
                    for row in table_rows:
                        columns = row.find_all(['th', 'td'])
                        row_data = []
                        for column in columns:
                            data = column.get_text().strip()
                            if data != "":
                                row_data.append(data.replace("\xa0", "").replace("+ ", "").replace("â‚¬","€"))
                        if len(row_data) > 0:
                            if len(row_data) == 1 and heading_index <= (len(headings)-1) and row_data[0] != headings[heading_index] and '€' in row_data[0] and 'korting' not in row_data[0] and 'promo' not in row_data[0] and len(row_data[0]) < 10:
                                json_data[headings[heading_index]] = row_data[0]
                                heading_index += 1
                            else:
                                json_data[row_data[0]] = row_data[1:]
                        # table_data.append(row_data)
                    heading_index = 0
                    providerdetails_array.append(json_data)
                    #only first restult is needed, if all details are required, remove the break below
                    break
                if providerdetails_array:
                    result[sectionName] = providerdetails_array

            # Fallback parser for the new resultaten page layout.
            if section_name not in result:
                parsed = _parse_new_results_cards(soup, myenergy_url, yearly_consumption, section_name)
                if parsed:
                    result.update(parsed)
        return result


# #test
# session = ComponentSession()

# config = {"postalcode": "1000",
#           "electricity_digital_counter": False, 
#           "day_electricity_consumption":555, 
#           "night_electricity_consumption": 0,
#           "excl_night_electricity_consumption": 0,
#           "solar_panels": False, "electricity_injection": 0,
#           "electricity_injection_night": 0, 
#           "electricity_provider": "No provider", 
#           "inverter_power": 0, 
#           "combine_elec_and_gas": False, 
#           "gas_consumption": 15000, 
#           "gas_provider": "No provider", 
#           "directdebit_invoice": True, 
#           "email_invoice": True, 
#           "online_support": True, 
#           "electric_car": False}


# config = {"postalcode": "1190",
#           "electricity_digital_counter": True, 
#           "day_electricity_consumption":960, 
#           "night_electricity_consumption": 1400,
#           "excl_night_electricity_consumption": 0,
#           "solar_panels": False, "electricity_injection": 0,
#           "electricity_injection_night": 0, 
#           "electricity_provider": "No provider", 
#           "inverter_power": 0, 
#           "combine_elec_and_gas": False, 
#           "gas_consumption": 17000, 
#           "gas_provider": "No provider", 
#           "directdebit_invoice": True, 
#           "email_invoice": True, 
#           "online_support": True, 
#           "electric_car": False}


# # print(session.get_data(config, ContractType.FIXED))
# print(session.get_data(config, ContractType.VARIABLE))

