"""Automation Monitor - detects failed automation runs, exposes them as a
sensor; also proactively flags entities referenced by automations/scripts
that are stuck unavailable (see linked_entities_coordinator.py)."""

from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ENTITY_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_REBUILD_LINKED_ENTITIES,
    SERVICE_RESET,
)
from .coordinator import AutomationMonitorCoordinator
from .linked_entities_coordinator import LinkedEntitiesCoordinator

RESET_SERVICE_SCHEMA = vol.Schema({
    vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
})


@dataclass
class AutomationMonitorRuntimeData:
    """Everything this config entry needs at runtime - both sensors'
    coordinators, kept fully independent of each other (see
    linked_entities_coordinator.py docstring for why)."""

    failures: AutomationMonitorCoordinator
    linked_entities: LinkedEntitiesCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    failures_coordinator = AutomationMonitorCoordinator(hass)
    failures_coordinator.async_setup()

    linked_entities_coordinator = LinkedEntitiesCoordinator(hass, entry)
    linked_entities_coordinator.async_setup()

    runtime_data = AutomationMonitorRuntimeData(
        failures=failures_coordinator, linked_entities=linked_entities_coordinator
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def _async_handle_reset(call: ServiceCall) -> None:
        target_entity_id = call.data.get(ATTR_ENTITY_ID)
        if target_entity_id:
            failures_coordinator.data.pop(target_entity_id, None)
        else:
            failures_coordinator.data.clear()
        failures_coordinator.async_set_updated_data(failures_coordinator.data)

    async def _async_handle_rebuild_linked_entities(call: ServiceCall) -> None:
        await linked_entities_coordinator.async_rebuild()

    # Single-instance-only integration (see config_flow.py), so registering
    # once here - keyed off this closure's coordinators - against the whole
    # hass.services registry is safe: there's never more than one entry.
    hass.services.async_register(
        DOMAIN, SERVICE_RESET, _async_handle_reset, schema=RESET_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REBUILD_LINKED_ENTITIES, _async_handle_rebuild_linked_entities
    )

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Simplest, most robust way to apply a changed threshold: re-run
    # async_setup_entry from scratch rather than re-timing in-flight
    # per-entity timers live.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime_data: AutomationMonitorRuntimeData = hass.data[DOMAIN].pop(entry.entry_id)
        runtime_data.failures.async_unload()
        runtime_data.linked_entities.async_unload()
        hass.services.async_remove(DOMAIN, SERVICE_RESET)
        hass.services.async_remove(DOMAIN, SERVICE_REBUILD_LINKED_ENTITIES)
    return unload_ok
