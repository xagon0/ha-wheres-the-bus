"""The Where's the Bus integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import WheresTheBusApi, WheresTheBusApiError, WheresTheBusAuthError, BusStatus, RiderInfo, StudentScan, normalized_name
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD
from .polling import polling_interval
from .identity import migrate_rider_entities

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = WheresTheBusApi(
        email=entry.data[CONF_EMAIL], password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass), device_id=f"HomeAssistant_{entry.entry_id}",
    )
    try:
        await api.authenticate()
    except WheresTheBusAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except WheresTheBusApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    migrate_rider_entities(hass, entry, api.riders)
    coordinator = WheresTheBusCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"api": api, "coordinator": coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["api"].close()
    return unload_ok


class WheresTheBusCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, api: WheresTheBusApi, entry: ConfigEntry) -> None:
        self.api = api
        self.entry = entry
        self._riders = api.riders
        self._bus_status: dict[str, BusStatus] = {}
        self._student_scans: list[StudentScan] = []
        self.scans_available = False
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(seconds=polling_interval(dt_util.now(), entry.options)))

    @property
    def riders(self) -> list[RiderInfo]:
        return self._riders

    def get_bus_status(self, student_id: str) -> BusStatus | None:
        return self._bus_status.get(student_id)

    def get_student_scans(self, student_name: str | None = None) -> list[StudentScan]:
        if not self.scans_available:
            return []
        if student_name is None:
            return self._student_scans
        return [s for s in self._student_scans if normalized_name(s.student_name) == normalized_name(student_name)]

    def get_latest_scan(self, student_name: str) -> StudentScan | None:
        return max(self.get_student_scans(student_name), key=lambda s: s.scan_time, default=None)

    async def _async_update_data(self) -> dict[str, BusStatus]:
        self.update_interval = timedelta(seconds=polling_interval(dt_util.now(), self.entry.options))
        try:
            statuses = {}
            for rider in self._riders:
                statuses[rider.student_id] = await self.api.get_bus_status(rider.student_id)
            self._bus_status = statuses
            try:
                self._student_scans = await self.api.get_student_scans()
                self.scans_available = True
            except WheresTheBusAuthError:
                raise
            except WheresTheBusApiError as err:
                self.scans_available = False
                _LOGGER.warning("Unable to update student scans: %s", err)
            return statuses
        except WheresTheBusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WheresTheBusApiError as err:
            raise UpdateFailed(str(err)) from err


async def async_remove_config_entry_device(hass, entry, device_entry) -> bool:
    """Allow removal of retired devices, protecting currently registered riders."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data is None:
        return False
    active = {
        (DOMAIN, f"{entry.entry_id}_student_{rider.student_id}")
        for rider in data["coordinator"].riders
    }
    return not bool(device_entry.identifiers & active)
