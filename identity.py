"""Preserve entity IDs while moving identity from names to student IDs."""
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .api import normalized_name
from .const import DOMAIN


def stable_rider_id(rider):
    return f"student_{rider.student_id}"


def migrate_rider_entities(hass, entry, riders):
    """Keep the active legacy entities, even if the provider changed spacing."""
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    for rider in riders:
        stable = stable_rider_id(rider)
        for kind in ("eta_minutes", "eta_time", "distance", "status", "last_scan", "tracker"):
            unique_id = f"{entry.entry_id}_{stable}_{kind}"
            if any(e.unique_id == unique_id for e in entities):
                continue
            prefix, suffix = f"{entry.entry_id}_", f"_{kind}"
            matches = [e for e in entities
                       if e.platform == DOMAIN and e.unique_id.startswith(prefix)
                       and e.unique_id.endswith(suffix)
                       and normalized_name(e.unique_id[len(prefix):-len(suffix)].replace("_", " ")) == normalized_name(rider.name)]
            enabled = [e for e in matches if e.disabled_by is None]
            candidates = enabled or matches
            # Do not guess between multiple active devices with the same name.
            if len(candidates) != 1:
                continue
            old = candidates[0]
            if old.device_id and (device := devices.async_get(old.device_id)):
                devices.async_update_device(
                    old.device_id,
                    new_identifiers=device.identifiers | {(DOMAIN, f"{entry.entry_id}_{stable}")},
                )
            registry.async_update_entity(old.entity_id, new_unique_id=unique_id)
