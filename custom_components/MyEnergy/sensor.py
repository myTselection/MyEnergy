import logging
import asyncio
from datetime import date, datetime, timedelta
from .utils import *

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity, SensorDeviceClass
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity
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
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string
    }
)

MIN_TIME_BETWEEN_UPDATES = timedelta(hours=1)


async def dry_setup(hass, config_entry, async_add_devices):
    config = config_entry

    check_settings(config, hass)
    sensors = []
    
    componentData = ComponentData(
        config,
        hass
    )
    await componentData._forced_update()
    assert componentData._details is not None

    sensorPoints = ComponentPointsSensor(componentData)
    sensors.append(sensorPoints)
    sensorAssistance = ComponentAssistanceSensor(componentData)
    sensors.append(sensorAssistance)
    sensorTransactions = ComponentTransactionsSensor(componentData)
    sensors.append(sensorTransactions)

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
        self._cardnumber = config.get(CONF_USERNAME)
        self._password = config.get(CONF_PASSWORD)
        self._details = None

    @property
    def unique_id(self):
        return f"{DOMAIN}-{self._cardnumber}"

    # same as update, but without throttle to make sure init is always executed
    async def _forced_update(self):
        _LOGGER.info("Fetching init stuff for " + NAME)
        if not(self._session):
            self._session = ComponentSession()

        if self._session:
            _LOGGER.debug("Starting with session for " + NAME)
            self._details = await self._hass.async_add_executor_job(lambda: self._session.login(self._cardnumber, self._password))
            _LOGGER.debug("login completed " + NAME)
            self._transactions = await self._hass.async_add_executor_job(lambda: self._session.transactions())
            _LOGGER.debug(f"transactions completed {NAME}, transactions: {self._transactions}")

        else:
            _LOGGER.debug(f"{NAME} no session available")

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def _update(self):
        await self._forced_update()

    async def update(self):
        # force update if (some) values are still unknown
        if self._details is None:
            await self._forced_update()
        else:
            await self._update()

    def clear_session(self):
        self._session : None

class ComponentPointsSensor(Entity):
    def __init__(self, data):
        self._data = data
        self._details = data._details
        self._last_update =  self._details.get('last_update')
        self._points = int(self._details.get('points'))
        self._cardNb = self._data._cardnumber
        # Calculate the number of fuel cards of each value
        self._cards_25_points = 950
        self._cards_15_points = 580
        self._cards_25 = self._points // 950
        remaining_points = self._points % 950
        self._cards_15 = remaining_points // 580

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._points

    async def async_update(self):
        await self._data.update()
        self._last_update =  self._details.get('last_update')
        self._points = int(self._details.get('points'))
        self._cardNb = self._data._cardnumber
        # Calculate the number of fuel cards of each value
        self._cards_25 = self._points // 950
        remaining_points = self._points % 950
        self._cards_15 = remaining_points // 580

    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        _LOGGER.info("async_will_remove_from_hass " + NAME)
        self._details.clear_session()

    @property
    def icon(self) -> str:
        """Shows the correct icon for container."""
        return "mdi:gas-station"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{self._data.unique_id}-points"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{NAME} Points {self._cardNb}"

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        return {
            ATTR_ATTRIBUTION: NAME,
            "last update": self._last_update,
            "points": self._points,
            "happy_fuel_card": f"Eligible Card 25€: {self._cards_25} ({self._cards_25_points} points), Card 15€: {self._cards_15} ({self._cards_15_points}  points)",
            "card_nr": self._cardNb
        }

    @property
    def device_info(self) -> dict:
        """Device info dictionary."""
        return {
            "identifiers": {(DOMAIN, self._data.unique_id)},
            "name": f"{NAME} {self._cardNb}",
            "manufacturer": DOMAIN,
        }

    @property
    def unit(self) -> int:
        """Unit"""
        return int

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement this sensor expresses itself in."""
        return "points"

    @property
    def device_class(self):
        return SensorDeviceClass.MONETARY

    @property
    def friendly_name(self) -> str:
        return self.unique_id


class ComponentAssistanceSensor(Entity):
    def __init__(self, data):
        self._data = data
        self._details = data._details
        self._last_update =  self._details.get('last_update')
        self._assistance = self._details.get('dtFinAssistance')
        self._cardNb = self._data._cardnumber
        self._assistance_coverage_date = convert_string_to_date(self._assistance)
        self._remaining_days = calculate_days_remaining(self._assistance_coverage_date)

    @property
    def state(self):
        """Return the state of the sensor."""
        return  self._remaining_days

    async def async_update(self):
        await self._data.update()
        self._last_update =  self._details.get('last_update')
        self._assistance = self._details.get('dtFinAssistance')
        self._cardNb = self._data._cardnumber
        self._assistance_coverage_date = convert_string_to_date(self._assistance)
        self._remaining_days = calculate_days_remaining(self._assistance_coverage_date)

    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        _LOGGER.info("async_will_remove_from_hass " + NAME)
        self._details.clear_session()

    @property
    def icon(self) -> str:
        """Shows the correct icon for container."""
        return "mdi:gas-station"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{self._data.unique_id}-assistance"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{NAME} Assistance {self._cardNb}"

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        return {
            ATTR_ATTRIBUTION: NAME,
            "last update": self._last_update,
            "assistance_coverage": self._assistance_coverage_date,
            "remaining_days": self._remaining_days,
            "card_nr": self._cardNb
        }

    @property
    def device_info(self) -> dict:
        """Device info dictionary."""
        return {
            "identifiers": {(DOMAIN, self._data.unique_id)},
            "name": f"{NAME} {self._cardNb}",
            "manufacturer": DOMAIN,
        }

    @property
    def unit(self) -> int:
        """Unit"""
        return int

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement this sensor expresses itself in."""
        return "days"

    @property
    def device_class(self):
        return SensorDeviceClass.DURATION

    @property
    def friendly_name(self) -> str:
        return self.unique_id

class ComponentTransactionsSensor(Entity):
    def __init__(self, data):
        self._data = data
        self._details = data._details
        self._transactions = data._transactions
        self._last_update =  self._details.get('last_update')
        self._assistance = self._details.get('dtFinAssistance')
        self._assistance_coverage_date = convert_string_to_date(self._assistance)
        self._cardNb = self._data._cardnumber
        _LOGGER.debug(f"transaction date: {self._transactions[0].get('date')}")
        self._lastTransactionDate = convert_string_to_date_yyyy_mm_dd(self._transactions[0].get('date'))

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._lastTransactionDate

    async def async_update(self):
        await self._data.update()
        self._last_update =  self._details.get('last_update')
        self._assistance = self._details.get('dtFinAssistance')
        self._assistance_coverage_date = convert_string_to_date(self._assistance)
        self._cardNb = self._data._cardnumber
        self._lastTransactionDate = convert_string_to_date_yyyy_mm_dd(self._transactions[0].get('date'))

    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        _LOGGER.info("async_will_remove_from_hass " + NAME)
        self._details.clear_session()

    @property
    def icon(self) -> str:
        """Shows the correct icon for container."""
        return "mdi:gas-station"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{self._data.unique_id}-transactions"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{NAME} Transactions {self._cardNb}"

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        return {
            ATTR_ATTRIBUTION: NAME,
            "last update": self._last_update,
            "assistance_coverage": self._assistance_coverage_date,
            "last_transaction_date": self._lastTransactionDate,
            "transactions": self._transactions,
            "card_nr": self._cardNb
        }

    @property
    def device_info(self) -> dict:
        """Device info dictionary."""
        return {
            "identifiers": {(DOMAIN, self._data.unique_id)},
            "name": f"{NAME} {self._cardNb}",
            "manufacturer": DOMAIN,
        }

    @property
    def unit(self) -> int:
        """Unit"""
        return date

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement this sensor expresses itself in."""
        return "date"

    @property
    def device_class(self):
        return SensorDeviceClass.TIMESTAMP

    @property
    def friendly_name(self) -> str:
        return self.unique_id
