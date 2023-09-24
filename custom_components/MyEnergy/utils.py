
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import urllib.parse

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.0%z"

gas_providers = {"No provider": "0","Social rate": "1000", "Aspiravi": "30", "Bolt": "29","DATS 24": "33", "Ebem": "13", "Ecopower": "14", "Elegant":"12", "Eneco": "15",
                 "Energie.be": "35", "Engie": "5", "Fluvius": "37", "Frank Energie": "41","Luminus": "9", "Mega": "21", "Octa+":  "19", "Tina":  "38", "TotalEnergies": "8", 
                 "Trevion": "3", "Wase Wind": "16", 'Wind voor "A"': "36", "Other": "1"}

electricity_providers = {"No provider": "0","Social rate": "1000", "Aspiravi": "30", "Bolt": "29","DATS 24": "33", "Ebem": "13", "Ecopower": "14", "Elegant":"12", "Eneco": "15",
                 "Energie.be": "35", "Engie": "5", "Fluvius": "37", "Frank Energie": "41","Luminus": "9", "Mega": "21", "Octa+":  "19", "Tina":  "38", "TotalEnergies": "8", 
                 "Trevion": "3", "Wase Wind": "16", 'Wind voor "A"': "36", "Other": "1"}

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

    def get_data(self, config):
        postalcode = config.get("postalcode")
        electricity_digital_counter = config.get("electricity_digital_counter")
        day_electricity_consumption = config.get("day_electricity_consumption",0)
        night_electricity_consumption = config.get("night_electricity_consumption", 0)
        excl_night_electricity_consumption = config.get("excl_night_electricity_consumption", 0)
        electricity_injection = config.get("electricity_injection", 0)
        electric_car = config.get("electric_car", False)
        
        gas_consumption = config.get("gas_consumption", 0)

        directdebit_invoice = config.get("directdebit_invoice", True)
        email_invoice = config.get("email_invoice", True)
        online_support = config.get("online_support", True)

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

        myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection}%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%21%7C%7C%7C%7C-{electric_car_n}%7C0-0"

        response = self.s.get(myenergy_url,timeout=30,allow_redirects=True)
        
        _LOGGER.debug("get result status code: " + str(response.status_code))
        _LOGGER.debug("get result response: " + str(response.text))
        soup = BeautifulSoup(response.text, 'html.parser')
        
        details = response.text
        return details

        