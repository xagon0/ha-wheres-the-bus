"""Sensor platform for Where's the Bus integration."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfTime
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
    """Set up Where's the Bus sensors."""
    coordinator: WheresTheBusCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SensorEntity] = []

    for rider in coordinator.riders:
        entities.extend([
            BusEtaMinutesSensor(coordinator, rider, entry),
            BusEtaTimeSensor(coordinator, rider, entry),
            BusDistanceSensor(coordinator, rider, entry),
            BusStatusSensor(coordinator, rider, entry),
            LastScanSensor(coordinator, rider, entry),
        ])

    async_add_entities(entities)


class WheresTheBusBaseSensor(CoordinatorEntity[WheresTheBusCoordinator], SensorEntity):
    """Base sensor for Where's the Bus."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WheresTheBusCoordinator,
        rider: RiderInfo,
        entry: ConfigEntry,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._rider = rider
        self._sensor_type = sensor_type
        # Use rider name for stable identifiers (API IDs can change between sessions)
        stable_id = _stable_rider_id(rider.name)
        self._attr_unique_id = f"{entry.entry_id}_{stable_id}_{sensor_type}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{stable_id}")},
            "name": f"{rider.name} School Bus",
            "manufacturer": "Where's the Bus",
            "model": f"Bus {rider.am_bus_no or rider.pm_bus_no or 'Unknown'}",
            "sw_version": "1.0",
        }


class BusEtaMinutesSensor(WheresTheBusBaseSensor):
    """Sensor for bus ETA in minutes."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: WheresTheBusCoordinator,
        rider: RiderInfo,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, rider, entry, "eta_minutes")
        self._attr_name = "ETA Minutes"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if status:
            return status.eta_minutes
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        return {
            "rider_name": self._rider.name,
            "school": self._rider.school,
            "bus_number": status.bus_number if status else None,
            "is_tracking": status.is_tracking if status else False,
        }


class BusEtaTimeSensor(WheresTheBusBaseSensor):
    """Sensor for bus arrival time."""

    _attr_icon = "mdi:bus-clock"

    def __init__(
        self,
        coordinator: WheresTheBusCoordinator,
        rider: RiderInfo,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, rider, entry, "eta_time")
        self._attr_name = "Arrival Time"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if status and status.eta_time:
            return status.eta_time
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        return {
            "am_stop_time": self._rider.am_stop_time,
            "pm_stop_time": self._rider.pm_stop_time,
            "am_stop_address": self._rider.am_stop_address,
            "pm_stop_address": self._rider.pm_stop_address,
        }


class BusDistanceSensor(WheresTheBusBaseSensor):
    """Sensor for bus distance away."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:map-marker-distance"

    def __init__(
        self,
        coordinator: WheresTheBusCoordinator,
        rider: RiderInfo,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, rider, entry, "distance")
        self._attr_name = "Distance Away"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if status:
            return status.distance_away
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if status and status.distance_unit:
            if status.distance_unit.lower() in ("km", "kilometers"):
                return UnitOfLength.KILOMETERS
            elif status.distance_unit.lower() in ("mi", "miles"):
                return UnitOfLength.MILES
        return UnitOfLength.KILOMETERS


class BusStatusSensor(WheresTheBusBaseSensor):
    """Sensor for overall bus status."""

    _attr_icon = "mdi:bus"

    def __init__(
        self,
        coordinator: WheresTheBusCoordinator,
        rider: RiderInfo,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, rider, entry, "status")
        self._attr_name = "Status"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        if not status:
            return "unknown"
        if status.is_tracking:
            if status.eta_minutes is not None and status.eta_minutes <= 2:
                return "arriving"
            return "tracking"
        # Check if tracking is suspended (overnight)
        if status.gps_status and "resumes" in status.gps_status.lower():
            return "suspended"
        if status.gps_status and "unavailable" in status.gps_status.lower():
            return "offline"
        return "not_tracking"

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        status = self.coordinator.get_bus_status(self._rider.child_id)
        attrs = {
            "rider_name": self._rider.name,
            "school": self._rider.school,
            "student_id": self._rider.student_id,
        }
        if status:
            attrs.update({
                "bus_number": status.bus_number,
                "bus_id": status.bus_id,
                "is_tracking": status.is_tracking,
                "gps_status": status.gps_status,
                "heading": status.heading,
                "speed": status.speed,
                "last_update": status.last_update,
            })
        return attrs


class LastScanSensor(WheresTheBusBaseSensor):
    """Sensor for last RFID/tablet scan."""

    _attr_icon = "mdi:card-account-details"

    def __init__(
        self,
        coordinator: WheresTheBusCoordinator,
        rider: RiderInfo,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, rider, entry, "last_scan")
        self._attr_name = "Last Scan"

    @property
    def native_value(self) -> str | None:
        """Return the state - scan method and time."""
        scan = self.coordinator.get_latest_scan(self._rider.name)
        if not scan:
            return "No scans today"

        # Convert timestamp to readable time
        scan_dt = datetime.fromtimestamp(scan.scan_time)
        time_str = scan_dt.strftime("%-I:%M %p")
        return f"{scan.scan_method} at {time_str}"

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        scan = self.coordinator.get_latest_scan(self._rider.name)
        attrs = {
            "rider_name": self._rider.name,
        }
        if scan:
            scan_dt = datetime.fromtimestamp(scan.scan_time)
            attrs.update({
                "scan_time": scan_dt.isoformat(),
                "scan_timestamp": scan.scan_time,
                "scan_location": scan.scan_location,
                "scan_method": scan.scan_method,
                "bus": scan.bus,
            })

        # Include all scans for today
        all_scans = self.coordinator.get_student_scans(self._rider.name)
        if all_scans:
            attrs["scans_today"] = [
                {
                    "time": datetime.fromtimestamp(s.scan_time).strftime("%-I:%M %p"),
                    "location": s.scan_location,
                    "method": s.scan_method,
                }
                for s in sorted(all_scans, key=lambda x: x.scan_time)
            ]

        return attrs
