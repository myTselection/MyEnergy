
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
    else:
        return True
    raise vol.Invalid("Missing settings to setup the sensor.")
        

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
        for type_comp in types_comp:
            section_name = _build_section_name(type_comp)
            yearly_consumption = day_electricity_consumption + night_electricity_consumption + excl_night_electricity_consumption if type_comp == "elektriciteit" else gas_consumption

            if manual_results_url:
                _LOGGER.debug(f"Using manual results URL: {manual_results_url}")
                response = self.s.get(manual_results_url, timeout=30, allow_redirects=True)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                parsed = _parse_new_results_cards(soup, manual_results_url, yearly_consumption, section_name)
                if parsed:
                    result.update(parsed)
                continue

            myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={type_comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection}%7C{electricity_injection_night}%7C{solar_panels_n}%7C%7C0%21{contract_type.code}%21A%21n%7C0%21{contract_type.code}%21A%7C{combine_elec_and_gas_n}%7C{inverter_power}%7C%7C%7C%7C%7C%21%7C%7C{inverter_power}%7C%7C{electric_car_n}-{electricity_provider_n}%7C{gas_provider_n}-0"
            
            _LOGGER.debug(f"myenergy_url: {myenergy_url}")
            response = self.s.get(myenergy_url,timeout=30,allow_redirects=True)
            response.raise_for_status()
            
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

