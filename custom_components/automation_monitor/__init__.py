"""Automation Monitor - detects failed automation runs, exposes them as a sensor."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import ATTR_ENTITY_ID, DOMAIN, PLATFORMS, SERVICE_RESET
from .coordinator import AutomationMonitorCoordinator

RESET_SERVICE_SCHEMA = vol.Schema({
    vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = AutomationMonitorCoordinator(hass)
    coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_handle_reset(call: ServiceCall) -> None:
        target_entity_id = call.data.get(ATTR_ENTITY_ID)
        if target_entity_id:
            coordinator.data.pop(target_entity_id, None)
        else:
            coordinator.data.clear()
        coordinator.async_set_updated_data(coordinator.data)

    # Single-instance-only integration (see config_flow.py), so registering
    # once here - keyed off this closure's coordinator - against the whole
    # hass.services registry is safe: there's never more than one entry.
    hass.services.async_register(
        DOMAIN, SERVICE_RESET, _async_handle_reset, schema=RESET_SERVICE_SCHEMA
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: AutomationMonitorCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_unload()
        hass.services.async_remove(DOMAIN, SERVICE_RESET)
    return unload_ok
