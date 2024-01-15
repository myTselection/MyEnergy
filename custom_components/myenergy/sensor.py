import logging
import asyncio
from datetime import date, datetime, timedelta
from .utils import *

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity, SensorDeviceClass
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.util import Throttle
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME
)

from . import DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)
_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.0%z"


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required("postalcode"): cv.string,
        vol.Optional("day_electricity_consumption"): cv.positive_int,
        vol.Optional("night_electricity_consumption"): cv.positive_int,
        vol.Optional("excl_night_electricity_consumption"): cv.positive_int,
        vol.Optional("electricity_injection"): cv.positive_int,
        vol.Optional("electricity_injection_night"): cv.positive_int,
        vol.Optional("gas_consumption"): cv.positive_int,
        vol.Required("directdebit_invoice"): cv.boolean,
        vol.Required("email_invoice"): cv.boolean,
        vol.Required("online_support"): cv.boolean,
        vol.Required("add_details"): cv.boolean,
        vol.Required("electric_car"): cv.boolean,
        vol.Required("combine_elec_and_gas"): cv.boolean,
        vol.Required("electricity_digital_counter"): cv.boolean,
        vol.Required("solar_panels"): cv.boolean,
        vol.Optional("inverter_power"): cv.positive_int
    }
)

MIN_TIME_BETWEEN_UPDATES = timedelta(hours=1)
# MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=5)


async def dry_setup(hass, config_entry, async_add_devices):
    config = config_entry
    postalcode = config.get("postalcode")
    
    day_electricity_consumption = config.get("day_electricity_consumption",0)
    night_electricity_consumption = config.get("night_electricity_consumption", 0)
    excl_night_electricity_consumption = config.get("excl_night_electricity_consumption", 0)
    electricity_injection = config.get("electricity_injection", 0)
    gas_consumption = config.get("gas_consumption", 0)
     

    check_settings(config, hass)
    sensors = []
    
    componentData = ComponentData(
        config,
        hass
    )
    await componentData._forced_update()
    assert componentData._details is not None

    
    electricity_comp = day_electricity_consumption != 0 or night_electricity_consumption != 0 or excl_night_electricity_consumption != 0 or electricity_injection != 0
    gas_comp = gas_consumption != 0


    if gas_comp:
        sensorGasFixed = ComponentSensor(componentData, postalcode, FuelType.GAS,ContractType.FIXED)
        sensors.append(sensorGasFixed)
        sensorGasVariable = ComponentSensor(componentData, postalcode, FuelType.GAS,ContractType.VARIABLE)
        sensors.append(sensorGasVariable)
    if electricity_comp:
        sensorElecFixed = ComponentSensor(componentData, postalcode, FuelType.ELECTRICITY,ContractType.FIXED)
        sensors.append(sensorElecFixed)
        sensorElecVariable = ComponentSensor(componentData, postalcode, FuelType.ELECTRICITY,ContractType.VARIABLE)
        sensors.append(sensorElecVariable)

    async_add_devices(sensors)


async def async_setup_platform(
    hass, config_entry, async_add_devices, discovery_info=None
):
    """Setup sensor platform for the ui"""
    _LOGGER.info("async_setup_platform " + NAME)
    await dry_setup(hass, config_entry, async_add_devices)
    return True


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Setup sensor platform for the ui"""
    _LOGGER.info("async_setup_entry " + NAME)
    config = config_entry.data
    await dry_setup(hass, config, async_add_devices)
    return True


async def async_remove_entry(hass, config_entry):
    _LOGGER.info("async_remove_entry " + NAME)
    try:
        await hass.config_entries.async_forward_entry_unload(config_entry, "sensor")
        _LOGGER.info("Successfully removed sensor from the integration")
    except ValueError:
        pass
        

def convert_string_to_date(string_date):
    day, month, year = map(int, string_date.split('/'))
    return date(year, month, day)

def convert_string_to_date_yyyy_mm_dd(string_date):
    year, month, day = map(int, string_date.split('/'))
    return date(year, month, day)

def calculate_days_remaining(target_date):
    today = date.today()
    remaining_days = (target_date - today).days
    return remaining_days

class ComponentData:
    def __init__(self, config, hass):
        self._config = config
        self._hass = hass
        self._session = ComponentSession()
        self._postalcode = config.get("postalcode")
        self._electricity_digital_counter = config.get("electricity_digital_counter")
        self._day_electricity_consumption = config.get("day_electricity_consumption",0)
        self._night_electricity_consumption = config.get("night_electricity_consumption", 0)
        self._excl_night_electricity_consumption = config.get("excl_night_electricity_consumption", 0)
        self._electricity_injection = config.get("electricity_injection", 0)
        self._electric_car = config.get("electric_car", False)
        self._gas_consumption = config.get("gas_consumption", 0)
        self._directdebit_invoice = config.get("directdebit_invoice", True)
        self._email_invoice = config.get("email_invoice", True)
        self._online_support = config.get("online_support", True)
        self._add_details = config.get("add_details", False)
        self._details = {}
        self._last_update = None
        self._refresh_required = True
        self._refresh_retry = 0

    @property
    def unique_id(self):
        return f"{NAME} {self._postalcode}"
    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self.unique_id

    # same as update, but without throttle to make sure init is always executed
    async def _forced_update(self):
        _LOGGER.info("Fetching init stuff for " + NAME)
        self._refresh_retry += 1
        if not(self._session):
            self._session = ComponentSession()
        
        self._last_update = datetime.now()
        for contract_type in ContractType:
            if self._session:
                _LOGGER.debug("Getting data for " + NAME)
                try:
                    self._details[contract_type.code] = await self._hass.async_add_executor_job(lambda: self._session.get_data(self._config, contract_type))
                    self._refresh_retry = 0
                    self._refresh_required = False
                except Exception as e:
                    # Log the exception details
                    _LOGGER.warning(f"An exception occurred, will retry: {str(e)}", exc_info=True)
                    self._refresh_required = True
                _LOGGER.debug("Data fetched completed " + NAME)
            else:
                _LOGGER.debug(f"{NAME} no session available")

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def _update(self):
        await self._forced_update()

    async def update(self):
        # force update if (some) values are still unknown
        if (self._details is None or self._details is {} or self._refresh_required) and self._refresh_retry < 5:
            await self._forced_update()
        else:
            await self._update()

    def clear_session(self):
        self._session : None

class ComponentSensor(Entity):
    def __init__(self, data, postalcode, fuel_type: FuelType, contract_type: ContractType):
        self._data = data
        self._details = data._details
        self._last_update =  self._data._last_update
        self._price = None
        self._priceyear = None
        self._kWhyear = None
        self._fuel_type = fuel_type
        self._fueltype_detail = None
        self._contract_type = contract_type
        self._postalcode = postalcode
        self._providerdetails = None
        self._url  = None
        self._providername = None
        self._contractname = None
        self._energycost = None
        self._netrate = None
        self._promo = None
        self._name = f"{NAME} {self._postalcode}"
        self._add_details = data._add_details

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._price

    async def async_update(self):
        await self._data.update()
        self._details = self._data._details        
        self._add_details = self._data._add_details
        self._last_update =  self._data._last_update
        self._name = f"{NAME} {self._postalcode} {self._fuel_type.fullnameEN} {self._contract_type.fullname}"
        self._contract_type_details = self._details.get(self._contract_type.code)
        # _LOGGER.debug(f"self._contract_type_details: {self._contract_type_details}")
        if self._contract_type_details == None:
            _LOGGER.warning(f"{NAME} requested contract type {self._contract_type.code} not found, available data: {self._details}")
            return
        for fueltype_name in self._contract_type_details.keys():
            if self._fuel_type.fullnameNL in fueltype_name:
                self._fueltype_detail = self._contract_type_details.get(fueltype_name)
                _LOGGER.debug(f"fueltype_detail: {self._contract_type} - {fueltype_name} - {self._fueltype_detail}")
                self._providerdetails = self._fueltype_detail[0]
                self._url = self._providerdetails.get('url',"")
                self._providername = self._providerdetails.get('provider',"")
                self._contractname = self._providerdetails.get('name',"")

                
                self._energycost = self._providerdetails.get(headings[0],"")
                self._netrate = self._providerdetails.get(headings[1],"")
                self._promo = self._providerdetails.get(headings[2],"")
                price_info = self._providerdetails.get('Jaarlijkse kostprijs',[])
                if len(price_info) > 0:
                    self._price = price_info[0]
                    self._price = self._price.replace('câ‚¬/kWh','').replace('c€/kWh','')
                    self._price = float(self._price.replace('.','').replace(',', '.'))/100
                    if len(price_info) >= 2:
                        self._kWhyear = price_info[1]
                        self._priceyear = price_info[2]
                        self._priceyear = self._priceyear.replace('câ‚¬/kWh','').replace('c€/kWh','')


    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        _LOGGER.info("async_will_remove_from_hass " + NAME)
        self._data.clear_session()

    @property
    def icon(self) -> str:
        """Shows the correct icon for container."""
        if self._fuel_type == FuelType.GAS:
            return "mdi:meter-gas"
        else:
            return "mdi:transmission-tower"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{self._data.unique_id} {self._fuel_type.fullnameEN} {self._contract_type.fullname}"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self.unique_id

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        return {
            ATTR_ATTRIBUTION: NAME,
            "last update": self._last_update,
            "postalcode": self._postalcode,
            "fuel type": self._fuel_type.fullnameEN,
            "contract type": self._contract_type.fullname,
            "url": self._url,
            "provider name": self._providername,
            "contract name": self._contractname,
            "energy cost": self._energycost,
            "netrate": self._netrate,
            "promo": self._promo,
            "total price per year": self._priceyear,
            "total kWh per year": self._kWhyear,
            "fulldetail": self._fueltype_detail if self._add_details else "details disabled in config"
        }

   
    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (NAME, self._data.unique_id)
            },
            name=self._data.name,
            manufacturer= NAME
        )

    @property
    def unit(self) -> int:
        """Unit"""
        return int

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement this sensor expresses itself in."""
        return "€/kWh"

    @property
    def device_class(self):
        return SensorDeviceClass.MONETARY

    @property
    def friendly_name(self) -> str:
        return self.unique_id
