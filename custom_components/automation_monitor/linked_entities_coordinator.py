"""Coordinator for the linked-entities-unavailable sensor.

Watches entities referenced by automations/scripts (including ones only
reached via a device or area target) and flags ones that have been
`unavailable` continuously for a configurable threshold - independent of
whether an automation using them has actually run. Complements the
trace-based AutomationMonitorCoordinator, which cannot see this failure
mode at all (see README "Known limitations"): HA's core service dispatch
silently skips unavailable entities, leaving nothing in a trace to
classify.

Fully independent from AutomationMonitorCoordinator - different trigger
model (state changes + timers vs. a single bus event), different data
shape. Kept as a separate coordinator/class specifically so this feature
can't regress the existing, live-verified trace/classification path.

Pure decision logic (safe to unit-test without HA installed) lives in
linked_entities.py; this file is the HA-touching half.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_UNAVAILABLE_THRESHOLD_MINUTES,
    DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES,
    DOMAIN,
    LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES,
)
from .linked_entities import (
    UNAVAILABLE_LIKE_STATES,
    build_reference_map,
    decide_transition,
    time_remaining_until_flag,
)

_LOGGER = logging.getLogger(__name__)

# Fired by the automation component on create/edit (covers essentially all
# automation-config changes made via the UI editor or the reload service -
# confirmed against the installed HA source). There is no equivalent event
# for scripts - see LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES in const.py
# for the periodic fallback that covers that gap. Re-verify against a live
# 2026.7.1 instance in case a script-reload event has since been added; if
# so, the periodic fallback can be dropped.
EVENT_AUTOMATION_RELOADED = "automation_reloaded"

_TRACKED_DOMAINS = ("automation", "script")
_TRACKED_ENTITY_PREFIXES = ("automation.", "script.")


def _referenced_entities_for(hass: HomeAssistant, domain: str, entity_id: str) -> set[str]:
    """Return every entity_id referenced by one automation/script,
    including ones reached only via a device or area target.

    Verified against the installed Home Assistant source
    (homeassistant/components/automation/__init__.py,
    homeassistant/components/script/__init__.py) - re-verify against a
    live 2026.7.1 instance before relying on this, per this project's
    convention:

    - `entities_in_automation`/`devices_in_automation`/`areas_in_automation`
      (and the `script` module's equivalents) are the same public
      functions that power HA's own "Related" tab in the automation/script
      editor - reused here instead of re-implementing config-walking.
    - Templated entity_id/device_id/area_id targets are NOT resolvable
      statically - HA's own `Script._find_referenced_entities` explicitly
      skips `template.Template` values. Same static-analysis limit
      Watchman already has for entity-existence checks, just for
      availability instead of existence.
    """
    if domain == "automation":
        from homeassistant.components.automation import (
            areas_in_automation,
            devices_in_automation,
            entities_in_automation,
        )

        direct = entities_in_automation(hass, entity_id)
        device_ids = devices_in_automation(hass, entity_id)
        area_ids = areas_in_automation(hass, entity_id)
    else:
        from homeassistant.components.script import (
            areas_in_script,
            devices_in_script,
            entities_in_script,
        )

        direct = entities_in_script(hass, entity_id)
        device_ids = devices_in_script(hass, entity_id)
        area_ids = areas_in_script(hass, entity_id)

    referenced: set[str] = set(direct)

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    # Device/area references are resolved to entity_ids via
    # entity_registry.async_entries_for_device/async_entries_for_area and
    # device_registry.async_entries_for_area (devices in an area -> their
    # entities). Disabled entities are excluded (default
    # include_disabled_entities=False).
    for device_id in device_ids:
        for entry in er.async_entries_for_device(ent_reg, device_id):
            referenced.add(entry.entity_id)

    for area_id in area_ids:
        for entry in er.async_entries_for_area(ent_reg, area_id):
            referenced.add(entry.entity_id)
        for device in dr.async_entries_for_area(dev_reg, area_id):
            for entry in er.async_entries_for_device(ent_reg, device.id):
                referenced.add(entry.entity_id)

    return referenced


def async_collect_source_entities(hass: HomeAssistant) -> dict[str, set[str]]:
    """Return {automation/script entity_id: {referenced entity_ids}} for
    every currently loaded automation and script."""
    source: dict[str, set[str]] = {}
    for domain in _TRACKED_DOMAINS:
        for entity_id in hass.states.async_entity_ids(domain):
            try:
                source[entity_id] = _referenced_entities_for(hass, domain, entity_id)
            except Exception:  # noqa: BLE001 - one bad entry shouldn't break the whole map
                _LOGGER.warning(
                    "Could not resolve references for %s, skipping it in "
                    "this rebuild",
                    entity_id,
                    exc_info=True,
                )
    return source


def async_build_reference_map(hass: HomeAssistant) -> dict[str, list[str]]:
    """HA-touching half of the reference-map build: collect + invert in
    one call. See linked_entities.build_reference_map for the pure half."""
    return build_reference_map(async_collect_source_entities(hass))


class LinkedEntitiesCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Holds entity_id -> unavailability-info for all currently flagged
    linked entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_linked_entities", update_interval=None
        )
        self.data: dict[str, dict[str, Any]] = {}
        self._entry = entry
        self._reference_map: dict[str, list[str]] = {}
        self._pending_timers: dict[str, CALLBACK_TYPE] = {}
        self._state_unsub: CALLBACK_TYPE | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def _threshold_minutes(self) -> int:
        return self._entry.options.get(
            CONF_UNAVAILABLE_THRESHOLD_MINUTES, DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES
        )

    @callback
    def async_setup(self) -> None:
        self._unsubs.append(
            self.hass.bus.async_listen(EVENT_AUTOMATION_RELOADED, self._handle_reload_event)
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_updated
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._handle_periodic_rebuild,
                timedelta(minutes=LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES),
            )
        )
        # Deferred so a full HA restart doesn't build the map before the
        # automation/script domains have finished loading their own
        # entities; fires immediately on a warm config-entry reload since
        # hass is already running by then.
        self._unsubs.append(async_at_started(self.hass, self._handle_started))

    @callback
    def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        for cancel in self._pending_timers.values():
            cancel()
        self._pending_timers.clear()

    async def async_rebuild(self) -> None:
        """Rebuild the reference map, resubscribe to state changes for the
        new tracked set, and reconcile currently-tracked/flagged entities
        against what changed."""
        new_map = async_build_reference_map(self.hass)
        old_tracked = set(self._reference_map)
        new_tracked = set(new_map)
        self._reference_map = new_map

        # Dropped from the map (their automation/script was deleted or no
        # longer references them): stop tracking, unflag if flagged.
        changed = False
        for entity_id in old_tracked - new_tracked:
            self._cancel_timer(entity_id)
            if entity_id in self.data:
                del self.data[entity_id]
                changed = True

        # Still in the map: refresh referenced_by in place if flagged (a
        # second automation may now also reference it, or vice versa).
        for entity_id in old_tracked & new_tracked:
            if entity_id in self.data:
                self.data[entity_id]["referenced_by"] = new_map[entity_id]

        # Resubscribe to the full new tracked set in one shot rather than
        # diffing the subscription itself - simpler and cheap at this size.
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        if new_tracked:
            self._state_unsub = async_track_state_change_event(
                self.hass, list(new_tracked), self._handle_state_change
            )

        # Newly added to the map: check current state now. If already
        # unavailable, there won't be a future transition event to hook,
        # so schedule/flag immediately using the *remaining* time since
        # its actual last_changed - not a fresh full threshold.
        for entity_id in new_tracked - old_tracked:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state in UNAVAILABLE_LIKE_STATES:
                self._schedule_or_flag(entity_id, state.last_changed)
                changed = True

        if changed:
            self.async_set_updated_data(self.data)

    @callback
    def _handle_reload_event(self, event: Event) -> None:
        self.hass.async_create_task(self.async_rebuild())

    @callback
    def _handle_registry_updated(self, event: Event) -> None:
        entity_id = event.data.get("entity_id", "")
        if entity_id.startswith(_TRACKED_ENTITY_PREFIXES):
            self.hass.async_create_task(self.async_rebuild())

    @callback
    def _handle_periodic_rebuild(self, now: datetime) -> None:
        self.hass.async_create_task(self.async_rebuild())

    async def _handle_started(self, hass: HomeAssistant) -> None:
        await self.async_rebuild()

    @callback
    def _handle_state_change(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        action = decide_transition(
            old_state.state if old_state else None,
            new_state.state if new_state else None,
        )

        if action == "start" and new_state is not None:
            self._schedule_or_flag(entity_id, new_state.last_changed)
        elif action == "cancel":
            self._cancel_timer(entity_id)
            if entity_id in self.data:
                del self.data[entity_id]
                self.async_set_updated_data(self.data)
        # "noop": attribute-only change, or both states unavailable-like -
        # don't touch the timer either way.

    @callback
    def _schedule_or_flag(self, entity_id: str, unavailable_since: datetime) -> None:
        self._cancel_timer(entity_id)
        remaining = time_remaining_until_flag(
            unavailable_since, dt_util.utcnow(), self._threshold_minutes
        )
        if remaining.total_seconds() <= 0:
            self._flag(entity_id, unavailable_since)
            return

        @callback
        def _fire(_now: datetime) -> None:
            self._pending_timers.pop(entity_id, None)
            self._flag(entity_id, unavailable_since)

        self._pending_timers[entity_id] = async_call_later(self.hass, remaining, _fire)

    @callback
    def _flag(self, entity_id: str, unavailable_since: datetime) -> None:
        state = self.hass.states.get(entity_id)
        self.data[entity_id] = {
            "entity_id": entity_id,
            "name": state.name if state else entity_id,
            "state": state.state if state else "unavailable",
            "unavailable_since": unavailable_since.isoformat(),
            "referenced_by": self._reference_map.get(entity_id, []),
        }
        self.async_set_updated_data(self.data)

    @callback
    def _cancel_timer(self, entity_id: str) -> None:
        cancel = self._pending_timers.pop(entity_id, None)
        if cancel is not None:
            cancel()
