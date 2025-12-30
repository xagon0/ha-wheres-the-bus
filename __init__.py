"""The Where's the Bus integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WheresTheBusApi, WheresTheBusApiError, BusStatus, RiderInfo, StudentScan
from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SUBDOMAIN,
    CONF_SHARD,
    DEFAULT_SUBDOMAIN,
    DEFAULT_SHARD,
    SCAN_INTERVAL_ACTIVE,
    SCAN_INTERVAL_IDLE,
    SCAN_INTERVAL_OFF,
    DEFAULT_AM_WINDOW,
    DEFAULT_PM_WINDOW,
    SCHOOL_DAYS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.DEVICE_TRACKER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Where's the Bus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)

    api = WheresTheBusApi(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        subdomain=entry.data.get(CONF_SUBDOMAIN, DEFAULT_SUBDOMAIN),
        shard=entry.data.get(CONF_SHARD, DEFAULT_SHARD),
        session=session,
    )

    try:
        await api.authenticate()
    except WheresTheBusApiError as err:
        _LOGGER.error("Failed to authenticate: %s", err)
        return False

    # Check if we found any riders
    if not api.riders:
        _LOGGER.error("No riders found after authentication. Check credentials and try again.")
        return False

    _LOGGER.info("Found %d rider(s): %s", len(api.riders), [r.name for r in api.riders])

    coordinator = WheresTheBusCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class WheresTheBusCoordinator(DataUpdateCoordinator):
    """Coordinator for Where's the Bus data updates."""

    def __init__(self, hass: HomeAssistant, api: WheresTheBusApi) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self._get_current_interval()),
        )
        self.api = api
        self._riders: list[RiderInfo] = []
        self._bus_status: dict[str, BusStatus] = {}
        self._student_scans: list[StudentScan] = []

    @staticmethod
    def _in_time_window(window: tuple[int, int, int, int]) -> bool:
        """Check if current time is within a window."""
        now = datetime.now()
        start = time(window[0], window[1])
        end = time(window[2], window[3])
        current = now.time()
        return start <= current <= end

    @staticmethod
    def _get_current_interval() -> int:
        """Determine the appropriate polling interval based on time/day."""
        now = datetime.now()

        # Check if it's a school day
        if now.weekday() not in SCHOOL_DAYS:
            _LOGGER.debug("Weekend - using off interval")
            return SCAN_INTERVAL_OFF

        # Check if we're in AM or PM window
        if (WheresTheBusCoordinator._in_time_window(DEFAULT_AM_WINDOW) or
            WheresTheBusCoordinator._in_time_window(DEFAULT_PM_WINDOW)):
            _LOGGER.debug("In active window - using active interval (15s)")
            return SCAN_INTERVAL_ACTIVE

        # Check if it's during school hours (between windows) - use idle
        am_end = time(DEFAULT_AM_WINDOW[2], DEFAULT_AM_WINDOW[3])
        pm_start = time(DEFAULT_PM_WINDOW[0], DEFAULT_PM_WINDOW[1])
        current = now.time()

        if am_end <= current <= pm_start:
            _LOGGER.debug("Between windows (school hours) - using idle interval (5 min)")
            return SCAN_INTERVAL_IDLE

        # Outside school hours on a school day
        # Before AM window or after PM window
        am_start = time(DEFAULT_AM_WINDOW[0], DEFAULT_AM_WINDOW[1])
        pm_end = time(DEFAULT_PM_WINDOW[2], DEFAULT_PM_WINDOW[3])

        if current < am_start or current > pm_end:
            _LOGGER.debug("Outside school hours - using off interval (1 hour)")
            return SCAN_INTERVAL_OFF

        return SCAN_INTERVAL_IDLE

    @property
    def riders(self) -> list[RiderInfo]:
        """Get the list of riders."""
        return self._riders

    def get_bus_status(self, child_id: str) -> BusStatus | None:
        """Get bus status for a specific child."""
        return self._bus_status.get(child_id)

    def get_student_scans(self, student_name: str | None = None) -> list[StudentScan]:
        """Get student scans, optionally filtered by name."""
        if student_name is None:
            return self._student_scans
        return [s for s in self._student_scans if s.student_name == student_name]

    def get_latest_scan(self, student_name: str) -> StudentScan | None:
        """Get the most recent scan for a student."""
        scans = self.get_student_scans(student_name)
        if scans:
            return max(scans, key=lambda s: s.scan_time)
        return None

    async def _async_update_data(self) -> dict[str, BusStatus]:
        """Fetch data from API."""
        try:
            # Adjust polling interval dynamically
            new_interval = self._get_current_interval()
            if self.update_interval.total_seconds() != new_interval:
                _LOGGER.info("Changing poll interval from %ds to %ds",
                           int(self.update_interval.total_seconds()), new_interval)
                self.update_interval = timedelta(seconds=new_interval)

            # Get riders if not already loaded
            if not self._riders:
                self._riders = self.api.riders

            # Update bus status for each rider
            for rider in self._riders:
                try:
                    status = await self.api.get_bus_status(rider.child_id)
                    if status:
                        self._bus_status[rider.child_id] = status
                except WheresTheBusApiError as err:
                    _LOGGER.warning(
                        "Failed to get bus status for %s: %s",
                        rider.name,
                        err,
                    )

            # Fetch student scans
            try:
                self._student_scans = await self.api.get_student_scans()
            except Exception as err:
                _LOGGER.warning("Failed to get student scans: %s", err)

            return self._bus_status

        except WheresTheBusApiError as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err
