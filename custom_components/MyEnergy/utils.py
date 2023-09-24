
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import urllib.parse

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.0%z"


def check_settings(config, hass):
    if not any(config.get(i) for i in ["username"]):
        _LOGGER.error("cardnumber was not set")
    else:
        return True
    if not config.get("password"):
        _LOGGER.error("password was not set")
    else:
        return True
    raise vol.Invalid("Missing settings to setup the sensor.")
        

class ComponentSession(object):
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Python/3"
        self.s.headers["Accept-Language"] = "en-US,en;q=0.9"

    def login(self, cardnumber, password):
        response = self.s.get("https://services.totalenergies.be/nl/inloggen-op-uw-club-account",timeout=30,allow_redirects=True)
        
        data = {
            "noCarte": cardnumber,
            "code": password,
            "p_LG": "NL",
            "p_PAYS": "BE",
            "menucourant": "adherent",
            "codeCategorie": ""
        }
        _LOGGER.debug(f"post data: {data}")
        response = self.s.post("https://club.totalenergies.be/authentification/authentification.php?PAYS=BE&LG=NL",data=data,timeout=30,allow_redirects=False)
        _LOGGER.debug("post result status code: " + str(response.status_code))
        _LOGGER.debug("post result response: " + str(response.text))
        _LOGGER.debug("post result cookies: " + str(self.s.cookies))
        
        clubCookie = self.s.cookies.get('club')
        clubCookie = urllib.parse.unquote(clubCookie)
        print(f"clubCookie: {clubCookie}")
        tab_valeurs = clubCookie.split(':')
        # Example nom: NAME, prenom: FIRSTNALE, email name@gmail.com, noEmetteur , noCarte , dtFinAssistance dd/mm/yyyy, phraseAssistance 0, points 999
        details = {
            "connect" : tab_valeurs[0],
            "lastname":  tab_valeurs[1],
            "firstname": tab_valeurs[2],
            "email" :tab_valeurs[3],
            "noEmetteur" : tab_valeurs[4],
            "noCarte" : tab_valeurs[5],
            "dtFinAssistance" : tab_valeurs[6],
            "phraseAssistance" : tab_valeurs[7],
            "points" : tab_valeurs[8],
            "last_update": datetime.now()
        }
        return details

    def transactions(self):
        response = self.s.get("https://club.totalenergies.be/adherent_transactions/transactions.php?PAYS=BE&LG=NL",timeout=30,allow_redirects=True)
        
        _LOGGER.debug("get result status code: " + str(response.status_code))
        _LOGGER.debug("get result response: " + str(response.text))
        _LOGGER.debug("get result cookies: " + str(self.s.cookies))
        
        soup = BeautifulSoup(response.text, 'html.parser')

        transactions = []
        table = soup.find('table')
        rows = table.find_all('tr')

        for row in rows:
            columns = row.find_all('td')
            if len(columns) == 4 and len(columns[0].contents) >= 2:
                transaction = {
                    'date': columns[0].contents[0],
                    'station': columns[0].contents[2],
                    'subject': columns[1].text.strip(),
                    'debit': int(columns[2].text.strip()),
                    'credit': int(columns[3].text.strip())
                }
                transactions.append(transaction)

        # result = {'transactions': transactions}
        # print(json_data = json.dumps(transactions, indent=4))
        return transactions
        