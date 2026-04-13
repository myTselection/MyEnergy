
import logging
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
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


def validate_manual_results_url(manual_results_url):
    if not manual_results_url:
        return True

    parsed_url = urllib.parse.urlparse(manual_results_url)
    if parsed_url.scheme not in ("http", "https"):
        raise vol.Invalid("manual_results_url must be a valid http(s) URL.")

    # Step URLs are input pages. They do not contain offer cards that parser needs.
    if re.search(r"/vergelijking/stap-\d+(?:/|$)", parsed_url.path):
        raise vol.Invalid(
            "manual_results_url points to a vergelijking step page. Use a resultaten/offers URL instead."
        )

    return True


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
    cards = soup.select("article")
    parsed_cards = []

    for card in cards:
        provider_img = card.select_one("img[alt]")
        provider_name = _normalize_provider_name(provider_img.get("alt", "") if provider_img else "")

        # The first heading in the card is usually the product/contract name.
        name_el = card.select_one("h2, h3, h4")
        contract_name = name_el.get_text(" ", strip=True) if name_el else ""

        card_text = card.get_text(" ", strip=True)
        annual_match = re.search(r"€\s*[0-9\.,]+\s*/\s*jaar", card_text, re.IGNORECASE)
        monthly_match = re.search(r"€\s*[0-9\.,]+\s*/\s*maand", card_text, re.IGNORECASE)

        annual_value = _extract_euro_value(annual_match.group(0) if annual_match else "")
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
                    f"{cents_per_kwh:.2f} c€/kWh",
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


def _build_simulation_payload(config, locality):
    day_electricity_consumption = config.get("day_electricity_consumption", 0)
    night_electricity_consumption = config.get("night_electricity_consumption", 0)
    excl_night_electricity_consumption = config.get("excl_night_electricity_consumption", 0)
    electricity_injection = config.get("electricity_injection", 0)
    electricity_injection_night = config.get("electricity_injection_night", 0)
    gas_consumption = config.get("gas_consumption", 0)

    electricity_comp = day_electricity_consumption != 0 or night_electricity_consumption != 0 or excl_night_electricity_consumption != 0
    gas_comp = gas_consumption != 0

    meter_type = "MONO" if night_electricity_consumption == 0 and excl_night_electricity_consumption == 0 else "BI"
    solar_panels = config.get("solar_panels", False)

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
        "meterType": meter_type,
        "exclusiveNightMeter": excl_night_electricity_consumption > 0,
        "digitalMeter": config.get("electricity_digital_counter", False),
        "solarPanels": solar_panels,
        "electricVehicle": config.get("electric_car", False),
    }

    if electricity_comp:
        payload["eAnnualDayConsumption"] = int(day_electricity_consumption)
        payload["eAnnualNightConsumption"] = int(night_electricity_consumption) if meter_type == "BI" else None
        payload["eAnnualExclusiveNightConsumption"] = int(excl_night_electricity_consumption) if excl_night_electricity_consumption > 0 else None
        payload["eAnnualDayInjection"] = int(electricity_injection) if solar_panels else None
        payload["eAnnualNightInjection"] = int(electricity_injection_night) if solar_panels and meter_type == "BI" else None

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
        json_data["Jaarlijkse kostprijs"] = [
            f"{cents_per_kwh:.2f} c€/kWh",
            f"{yearly_consumption} kWh/jaar",
            f"€ {annual_total:.2f}/jaar",
        ]
    else:
        json_data["Jaarlijkse kostprijs"] = [f"€ {annual_total:.2f}/jaar"]

    return {section_name: [json_data]}

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

    validate_manual_results_url(config.get("manual_results_url", ""))
    return True
        

class ComponentSession(object):
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Python/3"
        self.s.headers["Accept-Language"] = "en-US,en;q=0.9"

    def get_data(self, config, contract_type: ContractType):
        manual_results_url = config.get("manual_results_url", "")
        postalcode = config.get("postalcode")
        electricity_digital_counter = config.get("electricity_digital_counter", False)
        electricity_digital_counter_n = 1 if electricity_digital_counter == True else 0
        day_electricity_consumption = config.get("day_electricity_consumption",0)
        night_electricity_consumption = config.get("night_electricity_consumption", 0)
        excl_night_electricity_consumption = config.get("excl_night_electricity_consumption", 0)

        solar_panels = config.get("solar_panels", False)
        solar_panels_n = 1 if solar_panels == True else 0
        electricity_injection = config.get("electricity_injection", 0)
        electricity_injection_night = config.get("electricity_injection_night", 0)

        electricity_provider = config.get("electricity_provider", "No provider")
        electricity_provider_n = providers.get(electricity_provider,0)

        inverter_power = config.get("inverter_power", 0)
        inverter_power = str(inverter_power).replace(',','%2C').replace('.','%2C')

        combine_elec_and_gas = config.get("combine_elec_and_gas", False)     
        combine_elec_and_gas_n = 1 if combine_elec_and_gas == True else 0   
        
        gas_consumption = config.get("gas_consumption", 0)
        
        gas_provider = config.get("gas_provider", "No provider")
        gas_provider_n = providers.get(gas_provider,0)

        directdebit_invoice = config.get("directdebit_invoice", True)
        directdebit_invoice_n = 1 if directdebit_invoice == True else 0
        email_invoice = config.get("email_invoice", True)
        email_invoice_n = 1 if email_invoice == True else 0
        online_support = config.get("online_support", True)
        online_support_n = 1 if online_support == True else 0
        electric_car = config.get("electric_car", False)
        electric_car_n = 1 if electric_car == True else 0

        electricity_comp = day_electricity_consumption != 0 or night_electricity_consumption != 0 or excl_night_electricity_consumption != 0
        gas_comp = gas_consumption != 0

        types_comp = []
        if electricity_comp: 
            types_comp.append("elektriciteit")
        if gas_comp:
            types_comp.append("aardgas")
    
        elec_level = 0
        if night_electricity_consumption != 0:
            elec_level += 1
        if excl_night_electricity_consumption !=0:
            elec_level += 1

        result = {}

        simulation_data = None
        if not manual_results_url:
            locality_response = self.s.get(
                f"https://api.comparateur.be/zone/localities?zipCode={postalcode}",
                timeout=30,
                allow_redirects=True,
            )
            locality_response.raise_for_status()
            localities = locality_response.json()
            locality = None
            for candidate in localities:
                if str(candidate.get("zipCode")) == str(postalcode):
                    locality = candidate
                    break
            if locality is None and localities:
                locality = localities[0]

            if locality is not None:
                simulation_payload = _build_simulation_payload(config, locality)
                simulation_response = self.s.post(
                    "https://api.comparateur.be/energy/comparison/simulation",
                    json=simulation_payload,
                    timeout=30,
                    allow_redirects=True,
                )
                try:
                    simulation_response.raise_for_status()
                    simulation_data = simulation_response.json()
                except requests.exceptions.HTTPError as err:
                    # 422 means payload rejected by API validation. Keep flow alive and fallback
                    # to generated/manual results parsing instead of failing whole refresh.
                    if simulation_response.status_code == 422:
                        response_text = simulation_response.text or ""
                        response_snippet = response_text[:500]
                        _LOGGER.warning(
                            "Simulation API rejected payload with HTTP 422. Falling back to HTML parsing. "
                            "payload=%s response=%s",
                            simulation_payload,
                            response_snippet,
                        )
                        simulation_data = None
                    else:
                        raise err

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
                    continue

            if manual_results_url:
                _LOGGER.debug(f"Using manual results URL: {manual_results_url}")
                response = self.s.get(manual_results_url, timeout=30, allow_redirects=True)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                parsed = _parse_new_results_cards(soup, manual_results_url, yearly_consumption, section_name)
                if parsed:
                    result.update(parsed)
                    continue
                _LOGGER.warning(
                    "Manual results URL returned no parseable offers for %s, falling back to generated URL",
                    section_name,
                )

            myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={type_comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection}%7C{electricity_injection_night}%7C{solar_panels_n}%7C%7C0%21{contract_type.code}%21A%21n%7C0%21{contract_type.code}%21A%7C{combine_elec_and_gas_n}%7C{inverter_power}%7C%7C%7C%7C%7C%21%7C%7C{inverter_power}%7C%7C{electric_car_n}-{electricity_provider_n}%7C{gas_provider_n}-0"
            
            _LOGGER.debug(f"myenergy_url: {myenergy_url}")
            response = self.s.get(myenergy_url,timeout=30,allow_redirects=True)
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

