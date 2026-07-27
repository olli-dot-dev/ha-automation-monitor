"""Coordinator: listens for automation_triggered events, fetches the
resulting trace, classifies it, and holds the current failed-automations
state. Event-driven, no polling interval.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .classification import is_execution_failure
from .const import (
    CONF_ENTITY_STREAK_OVERRIDES,
    CONF_EXCLUDED_AUTOMATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_FAILURE_STREAK_THRESHOLD,
    DEFAULT_ENTITY_STREAK_OVERRIDES,
    DEFAULT_EXCLUDED_AUTOMATIONS,
    DEFAULT_EXCLUDED_LABELS,
    DEFAULT_FAILURE_STREAK_THRESHOLD,
    DOMAIN,
    EVENT_AUTOMATION_TRIGGERED,
    SCOPE_FAILED_AUTOMATIONS,
)
from .labels import entity_has_excluded_label

_LOGGER = logging.getLogger(__name__)

# How long to wait between polls for the trace to finish, and how many
# times to poll before giving up. Resolves the "fixed timeout vs. poll on
# running=False" open question from the spec in favour of polling.
#
# A first attempt used 0.5s x 10 (5s total) and was caught by live testing:
# an automation with an 8s `delay:` action never got classified at all -
# the poll gave up before the trace finished. 1s x 60 (60s total) covers
# realistic delay/wait actions. Automations that run longer than that
# (e.g. a multi-minute `wait_for_trigger` with no timeout) still won't be
# classified - accepted as a known MVP limit rather than polling
# indefinitely, which would leak a background task per trigger for a run
# that may never finish (e.g. an unbounded wait).
TRACE_POLL_INTERVAL = 1.0
TRACE_POLL_MAX_ATTEMPTS = 60


class AutomationMonitorCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Holds entity_id -> failure-info for all currently failed automations."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.data: dict[str, dict[str, Any]] = {}
        self._entry = entry
        self._remove_listener: Any = None
        # Consecutive-failure count per automation entity_id, purely
        # in-memory (not persisted across restarts, same as `.data` -
        # see README "A Home Assistant restart resets both sensors").
        # Only ever incremented/reset here in _async_process_trigger and
        # via reset(); never written to directly from __init__.py, unlike
        # `.data` (kept encapsulated since the reset service needs to
        # touch both together - see reset()).
        self._streaks: dict[str, int] = {}

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

    @property
    def _default_streak_threshold(self) -> int:
        return self._entry.options.get(
            CONF_FAILURE_STREAK_THRESHOLD, DEFAULT_FAILURE_STREAK_THRESHOLD
        )

    @property
    def _entity_streak_overrides(self) -> dict[str, int]:
        return self._entry.options.get(
            CONF_ENTITY_STREAK_OVERRIDES, DEFAULT_ENTITY_STREAK_OVERRIDES
        )

    def _effective_streak_threshold(self, entity_id: str) -> int:
        """How many consecutive failures `entity_id` needs before it's
        flagged - the global default, unless it directly references one
        or more entities with their own override (CONF_ENTITY_STREAK_OVERRIDES),
        in which case the *highest* matching override wins (if this
        automation touches several overridden entities, treat it as
        tolerantly as the flakiest one among them).

        Matched via HA's own `entities_in_automation` - direct entity_id
        references only (triggers/conditions/actions), same as the
        linked-entities sensor's *simplest* resolution path. Deliberately
        does NOT also resolve device/area targets the way
        linked_entities_coordinator.py's `_referenced_entities_for` does
        (domain-scoped device/area expansion) - that logic exists in a
        different module to stay independent of this one (see this
        file's module docstring), and duplicating its full complexity
        here for a threshold nice-to-have wasn't judged worth it. Known
        limitation: an automation that only reaches the overridden entity
        via a device/area target won't pick up its override.
        """
        overrides = self._entity_streak_overrides
        if not overrides:
            return self._default_streak_threshold
        from homeassistant.components.automation import entities_in_automation

        referenced = entities_in_automation(self.hass, entity_id)
        matched = [overrides[e] for e in referenced if e in overrides]
        if matched:
            return max(matched)
        return self._default_streak_threshold

    def reset(self, entity_id: str | None) -> None:
        """Clear a tracked failure (or all of them) and its streak count
        together - used by the automation_monitor.reset service. Streak
        must be cleared alongside `.data`, not left behind: otherwise a
        "reset" automation that had already reached its streak threshold
        would re-flag itself on its very next failure instead of needing
        a fresh streak from zero, silently defeating the point of the
        threshold right after a reset."""
        if entity_id:
            self.data.pop(entity_id, None)
            self._streaks.pop(entity_id, None)
        else:
            self.data.clear()
            self._streaks.clear()
        self.async_set_updated_data(self.data)

    @callback
    def async_setup(self) -> None:
        self._remove_listener = self.hass.bus.async_listen(
            EVENT_AUTOMATION_TRIGGERED, self._handle_automation_triggered
        )

    @callback
    def async_unload(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _handle_automation_triggered(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        if entity_id is None:
            return
        # A labeled automation is opted out of monitoring entirely (see
        # CONF_EXCLUDED_LABELS in const.py) - checked fresh on every
        # trigger rather than cached, so a label added/removed via the
        # dialog takes effect on the automation's very next run without
        # needing a reload.
        if entity_has_excluded_label(self.hass, entity_id, self._excluded_labels):
            return
        # Per-automation, per-sensor exclusion (CONF_EXCLUDED_AUTOMATIONS) -
        # narrower than a label: this automation only, only this sensor.
        # Checked fresh on every trigger, same as the label check above,
        # so an options change takes effect on the very next run without
        # a reload.
        if SCOPE_FAILED_AUTOMATIONS in self._excluded_automations.get(entity_id, []):
            return
        self.hass.async_create_task(self._async_process_trigger(entity_id))

    async def _async_process_trigger(self, entity_id: str) -> None:
        trace = await self._async_wait_for_finished_trace(entity_id)
        if trace is None:
            # Trace never showed up as finished, or reading it failed -
            # leave existing state untouched rather than guessing.
            return

        script_execution = trace.get("script_execution")
        last_step = trace.get("last_step")
        aborted_step_had_error = self._step_had_error(trace, last_step)

        if is_execution_failure(script_execution, aborted_step_had_error=aborted_step_had_error):
            streak = self._streaks.get(entity_id, 0) + 1
            self._streaks[entity_id] = streak
            threshold = self._effective_streak_threshold(entity_id)
            if streak >= threshold:
                # Refreshed every time this fires, even if already
                # flagged from an earlier failure in the same streak -
                # keeps last_error_time/error_message current rather
                # than frozen at whichever failure first crossed the
                # threshold.
                self.data[entity_id] = {
                    "entity_id": entity_id,
                    "name": self._async_get_name(entity_id),
                    "unique_id": self._async_get_unique_id(entity_id),
                    "last_error_time": datetime.now().astimezone().isoformat(),
                    "error_message": self._build_error_message(trace, last_step),
                    "error_step": last_step or "unknown",
                    "consecutive_failures": streak,
                }
            # else: below threshold - tracked in _streaks, not yet
            # surfaced in .data/the sensor. A threshold of 1 (default)
            # always flags on this branch, same as before this feature
            # existed.
        else:
            self._streaks.pop(entity_id, None)
            self.data.pop(entity_id, None)

        self.async_set_updated_data(self.data)

    def _async_get_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    def _async_get_unique_id(self, entity_id: str) -> str | None:
        """The automation's config `id:` (stable across renames) - not its
        entity_id's object_id. Used to link straight to the automation
        editor (`/config/automation/edit/<unique_id>`) from the optional
        Repairs issue, see issues.py. `None` if the
        entity isn't in the registry for some reason - callers fall back
        to a less specific link rather than erroring."""
        registry_entry = er.async_get(self.hass).async_get(entity_id)
        return registry_entry.unique_id if registry_entry else None

    @staticmethod
    def _step_had_error(trace: dict[str, Any], last_step: str | None) -> bool:
        # Only meaningful for script_execution == "aborted", see
        # classification.py docstring: HA explicitly clears the last
        # step's own error on a failed condition *action*, but sets it
        # for every other abort (e.g. `stop: ... error: true`). Only
        # visible in the extended trace's per-step data, not the short
        # trace.
        if last_step is None:
            return False
        steps = trace.get("trace", {}).get(last_step)
        if not steps:
            return False
        return steps[-1].get("error") is not None

    @staticmethod
    def _build_error_message(trace: dict[str, Any], last_step: str | None) -> str:
        # The top-level "error" is only set for script_execution=="error".
        # For an "aborted" failure (e.g. `stop: ... error: true`), the
        # message instead lives on the last step itself.
        if error := trace.get("error"):
            return str(error)
        if last_step:
            steps = trace.get("trace", {}).get(last_step) or []
            if steps and (step_error := steps[-1].get("error")):
                return str(step_error)
        return f"Aborted at step: {last_step or 'unknown'}"

    async def _async_wait_for_finished_trace(self, entity_id: str) -> dict[str, Any] | None:
        for _ in range(TRACE_POLL_MAX_ATTEMPTS):
            trace = self._get_last_trace(entity_id)
            if trace is not None and trace.get("state") == "stopped":
                return trace
            await asyncio.sleep(TRACE_POLL_INTERVAL)
        _LOGGER.debug(
            "Trace for %s did not finish within %.1fs, giving up",
            entity_id,
            TRACE_POLL_INTERVAL * TRACE_POLL_MAX_ATTEMPTS,
        )
        return None

    def _get_last_trace(self, entity_id: str) -> dict[str, Any] | None:
        """Fetch the most recent trace for an automation, as an extended dict.

        NOTE: reaches into `trace`/`automation` internals that are not a
        documented, stable public API and can change between HA versions
        without notice - wrapped defensively so a breaking change here
        degrades to "automation monitor stops updating" rather than
        crashing HA. Verified against Home Assistant 2026.7.1 source
        (homeassistant/components/trace, homeassistant/helpers/trace.py,
        homeassistant/components/automation/__init__.py) and a live test
        instance:

        - Traces are stored in hass.data[DATA_TRACE], keyed by
          "automation.<unique_id>" - the automation's *unique_id* (its
          config "id:", stable across renames), NOT its entity_id's
          object_id. Must resolve entity_id -> unique_id via the entity
          registry first.
        - Each bucket's `.runs` is an insertion-ordered, size-limited
          dict of run_id -> trace; the most recently added entry is the
          current run.
        - The *extended* dict (not the short one) is needed: telling a
          failed condition action apart from a real abort requires the
          per-step "error" field, which only the extended dict exposes
          under trace["trace"][<step path>].
        """
        try:
            from homeassistant.components.trace.const import DATA_TRACE

            registry_entry = er.async_get(self.hass).async_get(entity_id)
            if registry_entry is None or registry_entry.unique_id is None:
                return None
            trace_key = f"automation.{registry_entry.unique_id}"

            buckets = self.hass.data.get(DATA_TRACE, {}).get(trace_key)
            if buckets is None or not buckets.runs:
                return None

            last_trace = next(reversed(buckets.runs.values()))
            return last_trace.as_extended_dict()
        except Exception:  # noqa: BLE001 - deliberately broad, see docstring
            _LOGGER.warning(
                "Could not read trace for %s - Home Assistant may have "
                "changed its internal trace storage. Automation Monitor "
                "cannot classify this run.",
                entity_id,
                exc_info=True,
            )
            return None
