
import logging
import requests
import urllib.parse
# import json
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG)

class ComponentSession(object):
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Python/3"
        self.s.headers["Accept-Language"] = "en-US,en;q=0.9"


    def get_data(self, config):
        postalcode = config.get("postalcode")
        day_electricity_consumption = config.get("day_electricity_consumption",0)
        night_electricity_consumption = config.get("night_electricity_consumption", 0)
        excl_night_electricity_consumption = config.get("excl_night_electricity_consumption", 0)
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

        contract_types = ["F","V","A"]
        contract_type = "V"
        combine_elec_and_gas = False
        combine_elec_and_gas_n = 1 if combine_elec_and_gas == True else 0
        electricity_digital_counter = True
        electric_car = True
        electricity_digital_counter_n = 1 if electricity_digital_counter == True else 0
        electric_car_n = 1 if electric_car == True else 0
        electricity_electricity_injection = True
        electricity_injection_n = 1 if electricity_electricity_injection == True else 0

        # myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection_n}%7C%7C%7C%7C0%21{contract_type}%21A%21n%7C0%21{contract_type}%21A%7C{combine_elec_and_gas_n}%7C%7C%7C%7C%7C%7C%21%7C%7C%7C%7C-{electric_car_n}%7C0-0"
        # myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={comp}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C0-%7C%7C%7C%7C0%21{contract_type}%21A%21n%7C0%21{contract_type}%21A%7C{combine_elec_and_gas_n}%7C%7C%7C%7C%7C%7C%21%7C%7C%7C%7C-0%7C0-0"
        myenergy_url = f"https://www.mijnenergie.be/energie-vergelijken-3-resultaten-?Form=fe&e={comp}&d={electricity_digital_counter_n}&c=particulier&cp={postalcode}&i2={elec_level}----{day_electricity_consumption}-{night_electricity_consumption}-{excl_night_electricity_consumption}-1----{gas_consumption}----1-{directdebit_invoice_n}%7C{email_invoice_n}%7C{online_support_n}%7C1-{electricity_injection_n}%7C%7C%7C%7C0%21{contract_type}%21A%21n%7C0%21{contract_type}%21A%7C{combine_elec_and_gas_n}%7C%7C%7C%7C%7C%7C%21%7C%7C%7C%7C-{electric_car_n}%7C0-0"
        _LOGGER.debug(f"myenergy_url: {myenergy_url}")
        response = self.s.get(myenergy_url,timeout=30,allow_redirects=True)
        
        _LOGGER.debug("get result status code: " + str(response.status_code))
        # _LOGGER.debug("get result response: " + str(response.text))
        soup = BeautifulSoup(response.text, 'html.parser')
        
        #sections: electricty and gas
        # <div class="tab-pane fade in show active" id="RestultatelecNormal" role="tabpanel">
        #         <table class="cleantable">
                    # <thead></thead>
                    # <tbody></tbody>
        # sections = soup.find_all('div', class_='tab-content')

        
        result = {}

        
        # sections = soup.find_all('div', class_='container-fluid container-fluid-custom')
        # for section in sections:
        
        section_ids = []
        if electricity_comp:
            section_ids.append("RestultatElec")
        if gas_comp:
            section_ids.append("RestultatGas")
        if combine_elec_and_gas:
            section_ids = ["RestultatDualFuel"]
        for section_id in section_ids:
            section =  soup.find(id=section_id)

            sectionName = section.find("caption", class_="sr-only").text
            # providerdetails = section.find_all('tr', class_='cleantable_overview_row')
            providerdetails = section.find_all('div', class_='product_details')
            providerdetails_json = {}
            for providerdetail in providerdetails:
                providerdetails_name = providerdetail.find('div', class_='product_details__header').text
                providerdetails_name = providerdetails_name.replace('\n', '')
                # productdetails = section.find_all('div', class_='product_details__options')
                # for productdetail in productdetails:


                # Find all table rows and extract the data
                table_rows = providerdetail.find_all('tr')

                # Create a list to store the table data
                table_data = []
                json_data = []

                headings= ["Energiekosten", "Nettarieven en heffingen", "Promo via Mijnenergie"]
                heading_index = 0
                # Loop through the rows and extract the data into a dictionary
                for row in table_rows[:-1]:
                    columns = row.find_all(['th', 'td'])
                    row_data = []
                    for column in columns:
                        data = column.get_text().strip()
                        if data != "":
                            row_data.append(data.replace("\xa0", "").replace("+ ", ""))
                    if len(row_data) > 0:
                        json_item = {}
                        if len(row_data) == 1 and heading_index <= (len(headings)-1) and row_data[0] != headings[heading_index] :
                            json_item[headings[heading_index]] = row_data[0]
                            heading_index += 1
                        else:
                            json_item[row_data[0]] = row_data[1:]
                        json_data.append(json_item)
                    table_data.append(row_data)
                providerdetails_json[providerdetails_name]= json_data
                #only first restult is needed, if all details are required, remove the break below
                break
                # #only first restult is needed, if all details are required, remove the break below
                # break
            result[sectionName] = providerdetails_json
        return result

        
config = {"postalcode": 3300, "day_electricity_consumption":658, "night_electricity_consumption": 0, 
          "excl_night_electricity_consumption": 0,"gas_consumption": 15000,"directdebit_invoice": False,"email_invoice": False,"online_support": False}
cs = ComponentSession()
details = cs.get_data(config)
# print(details)