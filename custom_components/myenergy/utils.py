
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import urllib.parse
from enum import Enum


import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.0%z"


providers = {"No provider": "0","Social rate": "1000", "Aspiravi": "30", "Bolt": "29","Brusol": 34, "Cociter": 31, "DATS 24": "33", "Ebem": "13", "Ecopower": "14", "Elegant":"12", "Eneco": "15",
                 "Energie.be": "35", "Engie": "5", "Fluvius": "37", "Frank Energie": "41","Luminus": "9", "Mega": "21", "Octa+":  "19", "Tina":  "38", "TotalEnergies": "8", 
                 "Trevion": "3", "Wase Wind": "16", 'Wind voor "A"': "36", "Other": "1"}

headings= ["Energiekosten", "Nettarieven en heffingen", "Promo via Mijnenergie"]

class FuelType(Enum):
    GAS = ("G","Aardgas","Gas")
    ELECTRICITY = ("E","Elektriciteit","Electricty")
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
            myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={type_comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection}%7C{electricity_injection_night}%7C{solar_panels_n}%7C%7C0%21{contract_type.code}%21A%21n%7C0%21{contract_type.code}%21A%7C{combine_elec_and_gas_n}%7C{inverter_power}%7C%7C%7C%7C%7C%21%7C%7C{inverter_power}%7C%7C{electric_car_n}-{electricity_provider_n}%7C{gas_provider_n}-0"
            
            _LOGGER.debug(f"myenergy_url: {myenergy_url}")
            response = self.s.get(myenergy_url,timeout=30,allow_redirects=True)
            assert response.status_code == 200
            
            _LOGGER.debug("get result status code: " + str(response.status_code))
            # _LOGGER.debug("get result response: " + str(response.text))
            soup = BeautifulSoup(response.text, 'html.parser')


            
            # sections = soup.find_all('div', class_='container-fluid container-fluid-custom')
            # for section in sections:
            
            section_ids = []
            # if electricity_comp:
            #     section_ids.append("RestultatElec")
            # if gas_comp:
            #     section_ids.append("RestultatGas")
            # if combine_elec_and_gas:
            #     section_ids = ["RestultatDualFuel"]
            section_ids.append("ScrollResult")
            for section_id in section_ids:
                _LOGGER.debug(f"section_id {section_id}")
                section =  soup.find(id=section_id)
                # if section == None:
                    # continue

                # sectionName = section.find("caption", class_="sr-only").text
                sectionName = section.find("h3", class_="h4 text-strong").text
                sectionName = sectionName.replace('Resultaten ','').title()
                # providerdetails = section.find_all('tr', class_='cleantable_overview_row')
                providerdetails = section.find_all('div', class_='card-body')
                providerdetails_array = []
                for providerdetail in providerdetails:
                    providerdetails_name = providerdetail.find('li', class_='list-inline-item large-body-font-size text-strong mb-2 mb-sm-0').text
                    providerdetails_name = providerdetails_name.replace('\n', '')

                    # Find the <img> element within the specified <div> by class name
                    img_element = providerdetail.find('div', class_='provider-logo-lg').find('img')

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
                result[sectionName] = providerdetails_array
        return result

        