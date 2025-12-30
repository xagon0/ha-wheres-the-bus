"""Device tracker platform for Where's the Bus integration."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WheresTheBusCoordinator
from .api import RiderInfo
from .const import DOMAIN


def _stable_rider_id(name: str) -> str:
    """Generate a stable ID from rider name (lowercased, spaces to underscores)."""
    return name.lower().replace(" ", "_").replace("'", "")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Where's the Bus device trackers."""
    coordinator: WheresTheBusCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        BusDeviceTracker(coordinator, rider, entry)
        for rider in coordinator.riders
    ]

    async_add_entities(entities)


class BusDeviceTracker(CoordinatorEntity[WheresTheBusCoordinator], TrackerEntity):
    """Device tracker for a school bus."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bus-school"

    def __init__(
        self,
        coordinator: WheresTheBusCoordinator,
        rider: RiderInfo,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator)
        self._rider = rider
        # Use rider name for stable identifiers (API IDs can change between sessions)
        stable_id = _stable_rider_id(rider.name)
        self._attr_unique_id = f"{entry.entry_id}_{stable_id}_tracker"
        self._attr_name = "Bus Location"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{stable_id}")},
            "name": f"{rider.name} School Bus",
            "manufacturer": "Where's the Bus",
            "model": f"Bus {rider.am_bus_no or rider.pm_bus_no or 'Unknown'}",
            "sw_version": "1.0",
        }

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if status and status.is_tracking:
            return status.latitude
        return None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if status and status.is_tracking:
            return status.longitude
        return None

    @property
    def location_name(self) -> str | None:
        """Return a location name for the device."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if status:
            if not status.is_tracking:
                return "Not Tracking"
            if status.eta_minutes is not None and status.eta_minutes <= 2:
                return "Arriving Soon"
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        attrs = {
            "rider_name": self._rider.name,
            "school": self._rider.school,
            "am_stop_lat": self._rider.am_stop_lat,
            "am_stop_lon": self._rider.am_stop_lon,
            "pm_stop_lat": self._rider.pm_stop_lat,
            "pm_stop_lon": self._rider.pm_stop_lon,
        }
        if status:
            attrs.update({
                "bus_number": status.bus_number,
                "is_tracking": status.is_tracking,
                "eta_minutes": status.eta_minutes,
                "eta_time": status.eta_time,
                "distance_away": status.distance_away,
                "heading": status.heading,
                "speed": status.speed,
                "gps_status": status.gps_status,
            })
        return attrs
