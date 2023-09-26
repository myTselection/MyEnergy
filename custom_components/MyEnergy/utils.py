
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import urllib.parse
from enum import Enum

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.0%z"

gas_providers = {"No provider": "0","Social rate": "1000", "Aspiravi": "30", "Bolt": "29","DATS 24": "33", "Ebem": "13", "Ecopower": "14", "Elegant":"12", "Eneco": "15",
                 "Energie.be": "35", "Engie": "5", "Fluvius": "37", "Frank Energie": "41","Luminus": "9", "Mega": "21", "Octa+":  "19", "Tina":  "38", "TotalEnergies": "8", 
                 "Trevion": "3", "Wase Wind": "16", 'Wind voor "A"': "36", "Other": "1"}

electricity_providers = {"No provider": "0","Social rate": "1000", "Aspiravi": "30", "Bolt": "29","DATS 24": "33", "Ebem": "13", "Ecopower": "14", "Elegant":"12", "Eneco": "15",
                 "Energie.be": "35", "Engie": "5", "Fluvius": "37", "Frank Energie": "41","Luminus": "9", "Mega": "21", "Octa+":  "19", "Tina":  "38", "TotalEnergies": "8", 
                 "Trevion": "3", "Wase Wind": "16", 'Wind voor "A"': "36", "Other": "1"}


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
        electricity_digital_counter = config.get("electricity_digital_counter")
        day_electricity_consumption = config.get("day_electricity_consumption",0)
        night_electricity_consumption = config.get("night_electricity_consumption", 0)
        excl_night_electricity_consumption = config.get("excl_night_electricity_consumption", 0)
        electricity_injection = config.get("electricity_injection", 0)

        combine_elec_and_gas = config.get("combine_elec_and_gas", False)        
        
        gas_consumption = config.get("gas_consumption", 0)

        directdebit_invoice = config.get("directdebit_invoice", True)
        email_invoice = config.get("email_invoice", True)
        online_support = config.get("online_support", True)
        electric_car = config.get("electric_car", False)

        electricity_comp = day_electricity_consumption != 0 or night_electricity_consumption != 0 or excl_night_electricity_consumption != 0
        gas_comp = gas_consumption != 0

        if electricity_comp and gas_comp:
            comp = "elektriciteit-en-aardgas"
        elif electricity_comp: 
            comp = "elektriciteit"
        elif gas_comp:
            comp = "aardgas"
        else:
            comp = "elektriciteit-en-aardgas"
    
        elec_level = 0
        if night_electricity_consumption != 0:
            elec_level += 1
        if excl_night_electricity_consumption !=0:
            elec_level += 1

        directdebit_invoice_n = 1 if directdebit_invoice == True else 0
        email_invoice_n = 1 if email_invoice == True else 0
        online_support_n = 1 if online_support == True else 0
        electricity_digital_counter_n = 1 if electricity_digital_counter == True else 0
        electric_car_n = 1 if electric_car == True else 0
        electricity_injection_n = 1 if electricity_injection == True else 0

        combine_elec_and_gas_n = 1 if combine_elec_and_gas == True else 0

        myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection_n}%7C%7C%7C%7C0%21{contract_type.code}%21A%21n%7C0%21{contract_type.code}%21A%7C{combine_elec_and_gas_n}%7C%7C%7C%7C%7C%7C%21%7C%7C%7C%7C-{electric_car_n}%7C0-0"
        
        _LOGGER.debug(f"myenergy_url: {myenergy_url}")
        response = self.s.get(myenergy_url,timeout=30,allow_redirects=True)
        
        _LOGGER.debug("get result status code: " + str(response.status_code))
        # _LOGGER.debug("get result response: " + str(response.text))
        soup = BeautifulSoup(response.text, 'html.parser')

        result = {}

        
        # sections = soup.find_all('div', class_='container-fluid container-fluid-custom')
        # for section in sections:
        
        section_ids = ["RestultatElec", "RestultatGas"]
        if combine_elec_and_gas:
            section_ids = ["RestultatDualFuel"]
        for section_id in section_ids:
            section =  soup.find(id=section_id)

            sectionName = section.find("caption", class_="sr-only").text
            # providerdetails = section.find_all('tr', class_='cleantable_overview_row')
            providerdetails = section.find_all('div', class_='product_details')
            providerdetails_array = []
            for providerdetail in providerdetails:
                providerdetails_name = providerdetail.find('div', class_='product_details__header').text
                providerdetails_name = providerdetails_name.replace('\n', '')


                # Find all table rows and extract the data
                table_rows = providerdetail.find_all('tr')

                # Create a list to store the table data
                # table_data = []
                json_data = {}
                json_data['name'] = providerdetails_name
                json_data['url'] = myenergy_url

                headings= ["Energiekosten", "Nettarieven en heffingen", "Promo via Mijnenergie"]
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
                        if len(row_data) == 1 and row_data[0] != headings[heading_index]:
                            if json_data.get(headings[heading_index]) == None:
                                json_data[headings[heading_index]] = row_data[0]
                            heading_index += 1
                            heading_index = min(heading_index,len(headings)-1)
                        else:
                            json_data[row_data[0]] = row_data[1:]
                    # table_data.append(row_data)
                heading_index = 0
                providerdetails_array.append(json_data)
                #only first restult is needed, if all details are required, remove the break below
                break
            result[sectionName] = providerdetails_array
        return result

        