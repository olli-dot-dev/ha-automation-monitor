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
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    CONF_ACTION,
    CONF_CHOOSE,
    CONF_DEFAULT,
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ELSE,
    CONF_IF,
    CONF_PARALLEL,
    CONF_SEQUENCE,
    CONF_SERVICE_DATA,
    CONF_SERVICE_DATA_TEMPLATE,
    CONF_TARGET,
    CONF_THEN,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
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
    CONF_EXCLUDE_OFF_AUTOMATIONS,
    CONF_EXCLUDED_AUTOMATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_IGNORED_ENTITIES,
    CONF_UNAVAILABLE_THRESHOLD_MINUTES,
    DEFAULT_EXCLUDE_OFF_AUTOMATIONS,
    DEFAULT_EXCLUDED_AUTOMATIONS,
    DEFAULT_EXCLUDED_LABELS,
    DEFAULT_IGNORED_ENTITIES,
    DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES,
    DOMAIN,
    LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES,
    SCOPE_LINKED_ENTITIES_UNAVAILABLE,
)
from .labels import entity_has_excluded_label
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


def _extract_target_ids(data: Any, key: str) -> list[str]:
    """One target field (area_id/device_id) from a service-call step's
    target/data dict, as a list - handles both the single-string and
    list forms HA's schema allows. A templated (dynamic) value is
    neither a `str` nor a `list` (it's a `template.Template` instance) -
    falls through to `[]`, i.e. skipped rather than guessed, same as HA's
    own (module-private, so not importable) `Script._referenced_extract_ids`."""
    if not isinstance(data, dict):
        return []
    value = data.get(key)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    return []


def _domain_scoped_targets(
    sequence: list[dict[str, Any]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Walk one automation/script's already-validated action sequence
    (`entity.action_script.sequence` / `entity.script.sequence`),
    returning [(domain, area_id), ...] and [(domain, device_id), ...]
    pairs from actual service-call and device-automation steps only -
    deliberately not from conditions/triggers, see
    _referenced_entities_for for why.

    `domain` is the service/device-automation's own domain (e.g. "light"
    from a `light.turn_off` call), needed to correctly scope an area/
    device target: `light.turn_off` with `area_id: eg` only ever affects
    `light.*` entities in that area, never e.g. `media_player.*` ones
    merely also located there - see GitHub issue #1, which reported
    exactly that: a media_player falsely shown as "used by" several
    light/climate/cover automations that only shared its area, none of
    which ever call a media_player service.

    Mirrors the recursion structure of HA's own (module-private, so
    reimplemented rather than imported) `Script._find_referenced_devices`
    / `_find_referenced_target` (homeassistant/helpers/script.py,
    verified against the 2026.7.4 source) - re-verify against a live
    instance if this stops matching, same caveat as the rest of this
    project's reliance on HA-internal structure.

    A templated whole-step `action:` value (not a literal "domain.method"
    string) can't be domain-scoped statically either - skipped for that
    step, same as an unresolvable target value already is (see
    _extract_target_ids).
    """
    area_targets: list[tuple[str, str]] = []
    device_targets: list[tuple[str, str]] = []

    for step in sequence:
        try:
            action = cv.determine_script_action(step)
        except ValueError:
            continue

        if action == cv.SCRIPT_ACTION_CALL_SERVICE:
            service = step.get(CONF_ACTION)
            if not isinstance(service, str) or "." not in service:
                continue  # templated action string - not statically known
            call_domain = service.split(".", 1)[0]
            for data in (
                step.get(CONF_TARGET),
                step.get(CONF_SERVICE_DATA),
                step.get(CONF_SERVICE_DATA_TEMPLATE),
            ):
                area_targets += [
                    (call_domain, area_id)
                    for area_id in _extract_target_ids(data, ATTR_AREA_ID)
                ]
                device_targets += [
                    (call_domain, device_id)
                    for device_id in _extract_target_ids(data, ATTR_DEVICE_ID)
                ]

        elif action == cv.SCRIPT_ACTION_DEVICE_AUTOMATION:
            device_action_domain = step.get(CONF_DOMAIN)
            device_id = step.get(CONF_DEVICE_ID)
            if isinstance(device_action_domain, str) and isinstance(device_id, str):
                device_targets.append((device_action_domain, device_id))

        elif action == cv.SCRIPT_ACTION_CHOOSE:
            for choice in step.get(CONF_CHOOSE, []):
                sub_areas, sub_devices = _domain_scoped_targets(
                    choice.get(CONF_SEQUENCE, [])
                )
                area_targets += sub_areas
                device_targets += sub_devices
            if CONF_DEFAULT in step:
                sub_areas, sub_devices = _domain_scoped_targets(step[CONF_DEFAULT])
                area_targets += sub_areas
                device_targets += sub_devices

        elif action == cv.SCRIPT_ACTION_IF:
            sub_areas, sub_devices = _domain_scoped_targets(step.get(CONF_THEN, []))
            area_targets += sub_areas
            device_targets += sub_devices
            if CONF_ELSE in step:
                sub_areas, sub_devices = _domain_scoped_targets(step[CONF_ELSE])
                area_targets += sub_areas
                device_targets += sub_devices

        elif action == cv.SCRIPT_ACTION_PARALLEL:
            for sub_script in step.get(CONF_PARALLEL, []):
                sub_areas, sub_devices = _domain_scoped_targets(
                    sub_script.get(CONF_SEQUENCE, [])
                )
                area_targets += sub_areas
                device_targets += sub_devices

        elif action == cv.SCRIPT_ACTION_SEQUENCE:
            sub_areas, sub_devices = _domain_scoped_targets(
                step.get(CONF_SEQUENCE, [])
            )
            area_targets += sub_areas
            device_targets += sub_devices

    return area_targets, device_targets


def _action_sequence_for(
    hass: HomeAssistant, domain: str, entity_id: str
) -> list[dict[str, Any]]:
    """The already-validated action sequence for one automation/script
    entity - `entity.action_script.sequence` / `entity.script.sequence`,
    the same `Script` instance HA's own trigger/run path uses.
    `hass.data[domain]` is the domain's `EntityComponent` - "automation"/
    "script" are stable, unchanging domain names, same as elsewhere in
    this module (_TRACKED_DOMAINS), so no need to import the
    component's own DATA_COMPONENT/DOMAIN constant just to spell the
    same string differently.

    `[]` for an entity that failed validation
    (`UnavailableAutomationEntity`/`UnavailableScriptEntity` - has no
    action_script/script attribute at all) or isn't found - same
    "degrade to nothing extra, don't crash the rebuild" approach as the
    rest of this module."""
    component = hass.data.get(domain)
    if component is None:
        return []
    entity = component.get_entity(entity_id)
    if entity is None:
        return []
    script = getattr(entity, "action_script" if domain == "automation" else "script", None)
    if script is None:
        return []
    return script.sequence


def _referenced_entities_for(hass: HomeAssistant, domain: str, entity_id: str) -> set[str]:
    """Return every entity_id referenced by one automation/script,
    including ones reached only via a device or area target.

    Verified against the installed Home Assistant source
    (homeassistant/components/automation/__init__.py,
    homeassistant/components/script/__init__.py,
    homeassistant/helpers/script.py, homeassistant/components/search/
    __init__.py - all checked against 2026.7.4) - re-verify against a
    live instance before relying on this, per this project's convention:

    - `entities_in_automation`/`entities_in_script` (direct, literal
      entity_id references from anywhere - triggers, conditions,
      actions) are reused as-is - always a deliberate, correct
      reference regardless of domain.
    - Device/area targets are deliberately NOT resolved the
      domain-agnostic way HA's own `devices_in_automation`/
      `areas_in_automation` (and script equivalents) do it - those just
      collect raw area_id/device_id values from anywhere in the config,
      with no link back to which domain the action they came from
      actually calls. Naively expanding that to "every entity in this
      area/device" caused GitHub issue #1: a media_player falsely
      flagged as "used by" light/climate/cover automations that merely
      shared its area, none of which ever call a media_player service.
      This also corrected a prior claim in this docstring that the old
      approach matched HA's own "Related" tab - checked against
      `homeassistant/components/search/__init__.py`
      (`_async_search_device`): the Related tab only ever looks for
      *direct* device/entity references and never expands "an automation
      targets this area, entity X is also in that area" the way the old
      code here did, so the old approach was actually broader than HA's
      own UI, not equivalent to it.
    - Fix: `_domain_scoped_targets` walks the actual action sequence
      itself (service-call/device-automation steps only, not
      conditions/triggers) pairing each area_id/device_id target with
      the domain of the action it came from; only entities of that same
      domain in the area/device are then added as referenced.
    - Templated entity_id/device_id/area_id targets, and a templated
      whole `action:` string, are not resolvable statically either way -
      skipped, not guessed. Same static-analysis limit Watchman already
      has for entity-existence checks, just for availability instead of
      existence.
    """
    if domain == "automation":
        from homeassistant.components.automation import entities_in_automation

        direct = entities_in_automation(hass, entity_id)
    else:
        from homeassistant.components.script import entities_in_script

        direct = entities_in_script(hass, entity_id)

    referenced: set[str] = set(direct)

    sequence = _action_sequence_for(hass, domain, entity_id)
    area_targets, device_targets = _domain_scoped_targets(sequence)

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    # Device/area references are resolved to entity_ids via
    # entity_registry.async_entries_for_device/async_entries_for_area and
    # device_registry.async_entries_for_area (devices in an area -> their
    # entities), filtered to the calling action's own domain (see
    # docstring above). Disabled entities are excluded (default
    # include_disabled_entities=False).
    for target_domain, device_id in device_targets:
        for entry in er.async_entries_for_device(ent_reg, device_id):
            if entry.domain == target_domain:
                referenced.add(entry.entity_id)

    for target_domain, area_id in area_targets:
        for entry in er.async_entries_for_area(ent_reg, area_id):
            if entry.domain == target_domain:
                referenced.add(entry.entity_id)
        for device in dr.async_entries_for_area(dev_reg, area_id):
            for entry in er.async_entries_for_device(ent_reg, device.id):
                if entry.domain == target_domain:
                    referenced.add(entry.entity_id)

    return referenced


def async_collect_source_entities(
    hass: HomeAssistant,
    *,
    exclude_off_automations: bool = False,
    excluded_labels: set[str] | None = None,
    excluded_automations: dict[str, list[str]] | None = None,
) -> dict[str, set[str]]:
    """Return {automation/script entity_id: {referenced entity_ids}} for
    every currently loaded automation and script.

    `exclude_off_automations` only ever skips automations, never scripts -
    see CONF_EXCLUDE_OFF_AUTOMATIONS in const.py for why a script's "off"
    state can't be treated the same way (idle, not disabled). A
    label-excluded automation/script (see CONF_EXCLUDED_LABELS) is
    skipped as a source entirely - its referenced entities simply aren't
    added to the map via it (still tracked if another, non-excluded
    automation/script also references them). `excluded_automations`
    (CONF_EXCLUDED_AUTOMATIONS) does the same but per-automation and
    per-sensor - automation domain only (never scripts, same as
    exclude_off_automations - scripts weren't part of what was asked
    for), skipped only if this sensor's scope is in its list."""
    excluded_labels = excluded_labels or set()
    excluded_automations = excluded_automations or {}
    source: dict[str, set[str]] = {}
    for domain in _TRACKED_DOMAINS:
        for entity_id in hass.states.async_entity_ids(domain):
            if exclude_off_automations and domain == "automation":
                state = hass.states.get(entity_id)
                if state is not None and state.state == "off":
                    continue
            if domain == "automation" and SCOPE_LINKED_ENTITIES_UNAVAILABLE in excluded_automations.get(
                entity_id, []
            ):
                continue
            if entity_has_excluded_label(hass, entity_id, excluded_labels):
                continue
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


def async_build_reference_map(
    hass: HomeAssistant,
    ignored: set[str] | None = None,
    *,
    exclude_off_automations: bool = False,
    excluded_labels: set[str] | None = None,
    excluded_automations: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """HA-touching half of the reference-map build: collect + invert in
    one call. See linked_entities.build_reference_map for the pure half.

    A label-excluded *referenced* entity/device (as opposed to a
    label-excluded automation/script source, handled inside
    async_collect_source_entities) is folded into `ignored` here rather
    than filtered separately - reuses the pure build_reference_map's
    existing ignored-entity handling (and, via that, async_rebuild's
    existing "dropped from map -> unflag if flagged" cleanup) instead of
    duplicating it for a second exclusion mechanism."""
    excluded_labels = excluded_labels or set()
    source = async_collect_source_entities(
        hass,
        exclude_off_automations=exclude_off_automations,
        excluded_labels=excluded_labels,
        excluded_automations=excluded_automations,
    )
    ignored = set(ignored or ())
    if excluded_labels:
        referenced_ids = {rid for ids in source.values() for rid in ids}
        ignored |= {
            rid
            for rid in referenced_ids
            if entity_has_excluded_label(hass, rid, excluded_labels)
        }
    return build_reference_map(source, ignored)


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
        # Separate from _state_unsub above (which tracks *referenced*
        # entities for unavailability) - this one watches automation
        # entities themselves for on/off transitions, only subscribed
        # while _exclude_off_automations is on, see async_rebuild. Without
        # it, toggling an automation off/on wouldn't be picked up until
        # the next periodic rebuild (up to 20 minutes) - none of the
        # other rebuild triggers (automation_reloaded, entity registry
        # updates) fire for a plain state change.
        self._automation_toggle_unsub: CALLBACK_TYPE | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def _threshold_minutes(self) -> int:
        return self._entry.options.get(
            CONF_UNAVAILABLE_THRESHOLD_MINUTES, DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES
        )

    @property
    def _ignored_entities(self) -> set[str]:
        return set(
            self._entry.options.get(CONF_IGNORED_ENTITIES, DEFAULT_IGNORED_ENTITIES)
        )

    @property
    def _exclude_off_automations(self) -> bool:
        return self._entry.options.get(
            CONF_EXCLUDE_OFF_AUTOMATIONS, DEFAULT_EXCLUDE_OFF_AUTOMATIONS
        )

    @property
    def _excluded_labels(self) -> set[str]:
        return set(
            self._entry.options.get(CONF_EXCLUDED_LABELS, DEFAULT_EXCLUDED_LABELS)
        )

    @property
    def _excluded_automations(self) -> dict[str, list[str]]:
        return self._entry.options.get(
            CONF_EXCLUDED_AUTOMATIONS, DEFAULT_EXCLUDED_AUTOMATIONS
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
        if self._automation_toggle_unsub is not None:
            self._automation_toggle_unsub()
            self._automation_toggle_unsub = None
        for cancel in self._pending_timers.values():
            cancel()
        self._pending_timers.clear()

    async def async_rebuild(self) -> None:
        """Rebuild the reference map, resubscribe to state changes for the
        new tracked set, and reconcile currently-tracked/flagged entities
        against what changed."""
        exclude_off_automations = self._exclude_off_automations
        new_map = async_build_reference_map(
            self.hass,
            self._ignored_entities,
            exclude_off_automations=exclude_off_automations,
            excluded_labels=self._excluded_labels,
            excluded_automations=self._excluded_automations,
        )
        old_tracked = set(self._reference_map)
        new_tracked = set(new_map)
        self._reference_map = new_map

        # Re-subscribe to automation on/off transitions so toggling one
        # doesn't have to wait for the next periodic rebuild to take
        # effect - only while the option is actually on, and against the
        # *current* set of automation entities (covers newly-added ones
        # on the next rebuild too).
        if self._automation_toggle_unsub is not None:
            self._automation_toggle_unsub()
            self._automation_toggle_unsub = None
        if exclude_off_automations:
            automation_ids = list(self.hass.states.async_entity_ids("automation"))
            if automation_ids:
                self._automation_toggle_unsub = async_track_state_change_event(
                    self.hass, automation_ids, self._handle_automation_toggle
                )

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

    # No dedicated listener for label changes (added/removed via the
    # label-management dialog on an entity or device) - same gap as
    # script edits (see EVENT_AUTOMATION_RELOADED above): picked up by
    # the next periodic rebuild (LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES,
    # up to 20 min) or the rebuild_linked_entities service, not
    # immediately. A dedicated device/entity-registry listener would have
    # to fire on every registry update across all of hass to catch every
    # possible label change, not just automation/script ones (see
    # _handle_registry_updated below) - too broad for the benefit.

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
    def _handle_automation_toggle(self, event: Event) -> None:
        """An automation we're subscribed to (see async_rebuild) changed
        state - only relevant while exclude_off_automations is on. Full
        rebuild rather than a targeted update: a single automation
        flipping off/on can add or remove several referenced entities at
        once (all its target entities), same complexity as a config
        change, so there's no simpler partial update worth doing here."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        old = old_state.state if old_state else None
        new = new_state.state if new_state else None
        if old == new:
            return  # attribute-only noise, not an actual on/off transition
        self.hass.async_create_task(self.async_rebuild())

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
        registry_entry = er.async_get(self.hass).async_get(entity_id)
        referenced_by = self._reference_map.get(entity_id, [])
        self.data[entity_id] = {
            "entity_id": entity_id,
            "name": state.name if state else entity_id,
            "state": state.state if state else "unavailable",
            "device_id": registry_entry.device_id if registry_entry else None,
            "unavailable_since": unavailable_since.isoformat(),
            "referenced_by": referenced_by,
            "referenced_by_details": [
                self._async_describe_source(source_id) for source_id in referenced_by
            ],
        }
        self.async_set_updated_data(self.data)

    def _async_describe_source(self, source_entity_id: str) -> dict[str, Any]:
        """Name/unique_id/domain for one automation/script referencing a
        flagged entity - kept separate from the plain `referenced_by`
        entity_id list (unchanged, still what the sensor attribute and
        the README's example Markdown card use) so the Repairs issue
        (see issues.py, which links each source straight to its editor)
        can be enriched without changing that existing, documented
        attribute shape."""
        state = self.hass.states.get(source_entity_id)
        registry_entry = er.async_get(self.hass).async_get(source_entity_id)
        return {
            "entity_id": source_entity_id,
            "name": state.name if state else source_entity_id,
            "unique_id": registry_entry.unique_id if registry_entry else None,
            "domain": source_entity_id.split(".", 1)[0],
        }

    @callback
    def _cancel_timer(self, entity_id: str) -> None:
        cancel = self._pending_timers.pop(entity_id, None)
        if cancel is not None:
            cancel()
