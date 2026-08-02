"""Automation Monitor - detects failed automation runs, exposes them as a
sensor; also proactively flags entities referenced by automations/scripts
that are stuck unavailable (see linked_entities_coordinator.py)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_NAME
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir

from .const import (
    ATTR_ENTITY_ID,
    CONF_NOTIFY_FAILED_AUTOMATIONS,
    CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE,
    DEFAULT_NOTIFY,
    DOMAIN,
    EVENT_FAILURE_DETECTED,
    EVENT_FAILURE_RESOLVED,
    EVENT_LINKED_ENTITY_AVAILABLE,
    EVENT_LINKED_ENTITY_UNAVAILABLE,
    ISSUE_PREFIX_FAILED_AUTOMATION,
    ISSUE_PREFIX_LINKED_ENTITY_UNAVAILABLE,
    PLATFORMS,
    SERVICE_REBUILD_LINKED_ENTITIES,
    SERVICE_RESET,
)
from .coordinator import AutomationMonitorCoordinator
from .issues import failed_automation_placeholders, linked_entity_placeholders
from .linked_entities_coordinator import LinkedEntitiesCoordinator

_LOGGER = logging.getLogger(__name__)

RESET_SERVICE_SCHEMA = vol.Schema({
    vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
})


@dataclass
class AutomationMonitorRuntimeData:
    """Everything this config entry needs at runtime - all coordinators,
    kept fully independent of each other (see
    linked_entities_coordinator.py docstring for why)."""

    failures: AutomationMonitorCoordinator
    linked_entities: LinkedEntitiesCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    failures_coordinator = AutomationMonitorCoordinator(hass, entry)
    failures_coordinator.async_setup()

    linked_entities_coordinator = LinkedEntitiesCoordinator(hass, entry)
    linked_entities_coordinator.async_setup()

    runtime_data = AutomationMonitorRuntimeData(
        failures=failures_coordinator,
        linked_entities=linked_entities_coordinator,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Optional Repairs issues (Settings -> Repairs, admin-only) - one
    # toggle per sensor (see const.py). Re-derives the whole set of
    # wanted issue_ids from the coordinator's current data on every
    # update rather than tracking a diff across calls, same
    # reflects-current-state approach as the sensors themselves; see
    # _sync_issues for how that translates into
    # create/update/delete calls against the issue registry.
    @callback
    def _update_failed_automations_issues() -> None:
        _sync_issues(
            hass,
            prefix=ISSUE_PREFIX_FAILED_AUTOMATION,
            enabled=entry.options.get(CONF_NOTIFY_FAILED_AUTOMATIONS, DEFAULT_NOTIFY),
            current={
                entity_id: failed_automation_placeholders(info)
                for entity_id, info in failures_coordinator.data.items()
            },
            translation_key=ISSUE_PREFIX_FAILED_AUTOMATION,
        )

    @callback
    def _update_linked_entities_issues() -> None:
        _sync_issues(
            hass,
            prefix=ISSUE_PREFIX_LINKED_ENTITY_UNAVAILABLE,
            enabled=entry.options.get(
                CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE, DEFAULT_NOTIFY
            ),
            current={
                entity_id: linked_entity_placeholders(info)
                for entity_id, info in linked_entities_coordinator.data.items()
            },
            translation_key=ISSUE_PREFIX_LINKED_ENTITY_UNAVAILABLE,
        )

    entry.async_on_unload(
        failures_coordinator.async_add_listener(_update_failed_automations_issues)
    )
    entry.async_on_unload(
        linked_entities_coordinator.async_add_listener(_update_linked_entities_issues)
    )
    # Sync both issue sets to the coordinators' current state right away,
    # not just on the next update: a coordinator's `.data` is set directly
    # rather than via `async_set_updated_data()` at construction time (see
    # coordinator.py / linked_entities_coordinator.py `__init__`), so the
    # listeners above never fire on setup itself. Without this, an options
    # save (which reloads the whole config entry - see
    # `_async_options_updated`) silently resets both coordinators to empty
    # while leaving any already-open issue stale/orphaned - visibly wrong
    # once a real failure/unavailable entity had been reported before the
    # reload. Found via live testing on 2026-07-26 against the old
    # persistent-notification version of this same mechanism (the failed
    # automations sensor read 0 right after an options save, but the
    # notification still showed the pre-reload failure) - applies equally
    # here.
    _update_failed_automations_issues()
    _update_linked_entities_issues()

    # Logbook history (Settings -> Logbook, see logbook.py) - fires once per
    # flag/resolve *transition*. Tracks the previously-seen id set in a
    # plain closure variable, independent of the coordinators' own `.data`
    # (which only ever reflects *current* state) and of the Repairs-issue
    # toggles/registry above - this always runs, on-by-default like HA's
    # own `automation_triggered` event. Reset on every reload/restart (a
    # fresh, empty set): an already-broken automation still flagged right
    # after a restart fires "detected" again rather than staying silent
    # forever, consistent with this project's fully-stateless,
    # current-state-only design (see README "Usage") - the same tradeoff
    # already accepted for the Repairs-issue sync's initial full-reconcile
    # call above.
    _last_failed_ids: set[str] = set()
    _last_unavailable_ids: set[str] = set()

    @callback
    def _fire_failure_events() -> None:
        nonlocal _last_failed_ids
        current_ids = set(failures_coordinator.data)
        for entity_id in current_ids - _last_failed_ids:
            info = failures_coordinator.data[entity_id]
            hass.bus.async_fire(
                EVENT_FAILURE_DETECTED,
                {
                    ATTR_ENTITY_ID: entity_id,
                    ATTR_NAME: info["name"],
                    "error_message": info["error_message"],
                    "error_step": info["error_step"],
                },
            )
        for entity_id in _last_failed_ids - current_ids:
            state = hass.states.get(entity_id)
            hass.bus.async_fire(
                EVENT_FAILURE_RESOLVED,
                {
                    ATTR_ENTITY_ID: entity_id,
                    ATTR_NAME: state.name if state else entity_id,
                },
            )
        _last_failed_ids = current_ids

    @callback
    def _fire_linked_entity_events() -> None:
        nonlocal _last_unavailable_ids
        current_ids = set(linked_entities_coordinator.data)
        for entity_id in current_ids - _last_unavailable_ids:
            info = linked_entities_coordinator.data[entity_id]
            hass.bus.async_fire(
                EVENT_LINKED_ENTITY_UNAVAILABLE,
                {ATTR_ENTITY_ID: entity_id, ATTR_NAME: info["name"]},
            )
        for entity_id in _last_unavailable_ids - current_ids:
            state = hass.states.get(entity_id)
            hass.bus.async_fire(
                EVENT_LINKED_ENTITY_AVAILABLE,
                {
                    ATTR_ENTITY_ID: entity_id,
                    ATTR_NAME: state.name if state else entity_id,
                },
            )
        _last_unavailable_ids = current_ids

    entry.async_on_unload(
        failures_coordinator.async_add_listener(_fire_failure_events)
    )
    entry.async_on_unload(
        linked_entities_coordinator.async_add_listener(_fire_linked_entity_events)
    )
    _fire_failure_events()
    _fire_linked_entity_events()

    async def _async_handle_reset(call: ServiceCall) -> None:
        failures_coordinator.reset(call.data.get(ATTR_ENTITY_ID))

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
def _sync_issues(
    hass: HomeAssistant,
    *,
    prefix: str,
    enabled: bool,
    current: dict[str, dict[str, str]],
    translation_key: str,
) -> None:
    """Reconcile one sensor's set of Repairs issues (all issue_ids under
    this domain starting with `f"{prefix}:"`) against `current` - one
    issue per currently-failed automation / currently-unavailable linked
    entity, keyed by `f"{prefix}:{entity_id}"`. Unlike the old single
    persistent-notification-per-sensor approach, this needs an actual
    diff: entities no longer in `current` get their issue deleted,
    everything still/newly in `current` gets created-or-updated
    (`async_create_issue` replaces an existing issue under the same
    issue_id in place, same "safe to call every time" property the old
    notification_id re-creation had). `enabled=False` clears every issue
    under this prefix regardless of `current` - a disabled toggle must
    actually clear already-open issues, not just stop refreshing them.

    This runs as a coordinator listener (see async_setup_entry), called
    synchronously and unwrapped by HA's own coordinator update path - an
    uncaught exception here wouldn't just skip the issue sync, it could
    propagate out through async_set_updated_data into whatever triggered
    the update (a state change, a rebuild, the reset service...) and fail
    that too, silently as far as the issue itself is concerned. Caught
    and logged explicitly so an issue-sync bug can never take detection
    down with it, and so it's actually visible in the log instead of just
    "the Repairs entry didn't show up" with no trace."""
    try:
        issue_registry = ir.async_get(hass)
        existing_ids = {
            issue_id
            for (domain, issue_id) in issue_registry.issues
            if domain == DOMAIN and issue_id.startswith(f"{prefix}:")
        }
        wanted_ids = {f"{prefix}:{entity_id}" for entity_id in current} if enabled else set()

        for issue_id in existing_ids - wanted_ids:
            _LOGGER.debug("Deleting Repairs issue %s", issue_id)
            ir.async_delete_issue(hass, DOMAIN, issue_id)

        if enabled:
            for entity_id, placeholders in current.items():
                issue_id = f"{prefix}:{entity_id}"
                _LOGGER.debug("Creating/updating Repairs issue %s", issue_id)
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=translation_key,
                    translation_placeholders=placeholders,
                )
    except Exception:  # noqa: BLE001 - see docstring: must never break the coordinator update
        _LOGGER.exception("Failed to sync Repairs issues for prefix %s", prefix)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Simplest, most robust way to apply a changed threshold: re-run
    # async_setup_entry from scratch rather than re-timing in-flight
    # per-entity timers live.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Deliberately does NOT touch open Repairs issues here - this runs on
    # every reload (including the options-update reload above), not just
    # on an actual removal. Clearing them here made a saved options
    # change silently wipe active issues even though nothing about what
    # they reported had actually changed (this was a real bug in the
    # persistent-notification version of this mechanism, fixed in
    # v0.7.2 - same failure shape would apply here). Real remove-for-good
    # cleanup lives in async_remove_entry instead, which HA only calls
    # when the config entry is actually being deleted.
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
    # successful async_unload_entry) - not on a reload. Don't leave stale
    # Repairs issues behind once the integration that owns them is gone.
    issue_registry = ir.async_get(hass)
    for domain, issue_id in list(issue_registry.issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
