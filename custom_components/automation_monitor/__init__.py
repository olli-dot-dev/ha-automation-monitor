"""Automation Monitor - detects failed automation runs, exposes them as a
sensor; also proactively flags entities referenced by automations/scripts
that are stuck unavailable (see linked_entities_coordinator.py)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ENTITY_ID,
    CONF_NOTIFY_FAILED_AUTOMATIONS,
    CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE,
    DEFAULT_NOTIFY,
    DOMAIN,
    NOTIFICATION_ID_FAILED_AUTOMATIONS,
    NOTIFICATION_ID_LINKED_ENTITIES_UNAVAILABLE,
    PLATFORMS,
    SERVICE_REBUILD_LINKED_ENTITIES,
    SERVICE_RESET,
)
from .coordinator import AutomationMonitorCoordinator
from .linked_entities_coordinator import LinkedEntitiesCoordinator
from .notifications import build_failed_automations_message, build_linked_entities_message

_LOGGER = logging.getLogger(__name__)

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

    # Optional persistent notifications - one toggle per sensor (see
    # const.py). Re-derives the whole message from the coordinator's
    # current data on every update rather than diffing, same
    # reflects-current-state approach as the sensors themselves; see
    # notifications.py docstring for why re-creating under a fixed
    # notification_id is safe (updates in place, no duplicates).
    @callback
    def _update_failed_automations_notification() -> None:
        _async_sync_notification(
            hass,
            enabled=entry.options.get(CONF_NOTIFY_FAILED_AUTOMATIONS, DEFAULT_NOTIFY),
            notification_id=NOTIFICATION_ID_FAILED_AUTOMATIONS,
            title="Automation Monitor: failed automations",
            message=build_failed_automations_message(failures_coordinator.data),
        )

    @callback
    def _update_linked_entities_notification() -> None:
        _async_sync_notification(
            hass,
            enabled=entry.options.get(
                CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE, DEFAULT_NOTIFY
            ),
            notification_id=NOTIFICATION_ID_LINKED_ENTITIES_UNAVAILABLE,
            title="Automation Monitor: unavailable linked entities",
            message=build_linked_entities_message(linked_entities_coordinator.data),
        )

    entry.async_on_unload(
        failures_coordinator.async_add_listener(_update_failed_automations_notification)
    )
    entry.async_on_unload(
        linked_entities_coordinator.async_add_listener(_update_linked_entities_notification)
    )

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


@callback
def _async_sync_notification(
    hass: HomeAssistant,
    *,
    enabled: bool,
    notification_id: str,
    title: str,
    message: str,
) -> None:
    """Show or clear one persistent notification. Re-creating under the
    same notification_id updates the existing card in place instead of
    piling up duplicates. Dismissed (not just left stale) whenever the
    toggle is off or there's currently nothing to report - a disabled
    toggle must actually clear an already-shown notification, not just
    stop refreshing it.

    This runs as a coordinator listener (see async_setup_entry), called
    synchronously and unwrapped by HA's own coordinator update path - an
    uncaught exception here wouldn't just skip the notification, it could
    propagate out through async_set_updated_data into whatever triggered
    the update (a state change, a rebuild, the reset service...) and fail
    that too, silently as far as the notification itself is concerned.
    Caught and logged explicitly so a notification bug can never take
    detection down with it, and so it's actually visible in the log
    instead of just "the card didn't show up" with no trace."""
    try:
        if enabled and message:
            _LOGGER.debug(
                "Creating/updating persistent notification %s (%d chars)",
                notification_id,
                len(message),
            )
            persistent_notification.async_create(
                hass, message, title=title, notification_id=notification_id
            )
        else:
            _LOGGER.debug(
                "Dismissing persistent notification %s (enabled=%s, has_message=%s)",
                notification_id,
                enabled,
                bool(message),
            )
            persistent_notification.async_dismiss(hass, notification_id)
    except Exception:  # noqa: BLE001 - see docstring: must never break the coordinator update
        _LOGGER.exception(
            "Failed to sync persistent notification %s", notification_id
        )


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Simplest, most robust way to apply a changed threshold: re-run
    # async_setup_entry from scratch rather than re-timing in-flight
    # per-entity timers live.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Deliberately does NOT touch the persistent notifications here - this
    # runs on every reload (including the options-update reload above),
    # not just on an actual removal. Dismissing them here made a saved
    # options change silently wipe an active notification even though
    # nothing about what it reported had actually changed. Real
    # remove-for-good cleanup lives in async_remove_entry instead, which
    # HA only calls when the config entry is actually being deleted.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime_data: AutomationMonitorRuntimeData = hass.data[DOMAIN].pop(entry.entry_id)
        runtime_data.failures.async_unload()
        runtime_data.linked_entities.async_unload()
        hass.services.async_remove(DOMAIN, SERVICE_RESET)
        hass.services.async_remove(DOMAIN, SERVICE_REBUILD_LINKED_ENTITIES)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Called once the config entry is actually being deleted (after a
    # successful async_unload_entry) - not on a reload. Don't leave a
    # stale notification behind once the integration that owns it is gone.
    persistent_notification.async_dismiss(hass, NOTIFICATION_ID_FAILED_AUTOMATIONS)
    persistent_notification.async_dismiss(
        hass, NOTIFICATION_ID_LINKED_ENTITIES_UNAVAILABLE
    )
