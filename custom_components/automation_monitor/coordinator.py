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

from .classification import SCRIPT_EXECUTION_FINISHED, is_execution_failure
from .const import (
    CONF_ENTITY_STREAK_OVERRIDES,
    CONF_EXCLUDED_AUTOMATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_FAILURE_STREAK_THRESHOLD,
    CONF_IGNORED_ERROR_TEXTS,
    DEFAULT_ENTITY_STREAK_OVERRIDES,
    DEFAULT_EXCLUDED_AUTOMATIONS,
    DEFAULT_EXCLUDED_LABELS,
    DEFAULT_FAILURE_STREAK_THRESHOLD,
    DEFAULT_IGNORED_ERROR_TEXTS,
    DOMAIN,
    EVENT_AUTOMATION_TRIGGERED,
    SCOPE_FAILED_AUTOMATIONS,
)
from .labels import entity_has_excluded_label
from .trigger_fingerprint import trigger_fingerprint

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
    """Holds failure-info for every currently-failed (automation entity_id,
    triggering-trigger) pair - see GH #5. A consolidated automation with
    several independent triggers is really several independent pieces of
    logic sharing one entity_id: keying purely on entity_id (this
    project's original approach through v0.10.0) meant a successful run
    on one trigger's branch wrongly cleared a still-broken *other*
    trigger's branch, since both only ever wrote to the same slot. Both
    `.data` and `._streaks` below are keyed by `_path_key(entity_id,
    fingerprint)` instead - see trigger_fingerprint.py for what
    `fingerprint` identifies and why. The real entity_id is always still
    available from `info["entity_id"]` inside each `.data` value; nothing
    downstream (sensor.py, issues.py, __init__.py's event firing) needs to
    know or care that a key isn't a bare entity_id."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.data: dict[str, dict[str, Any]] = {}
        self._entry = entry
        self._remove_listener: Any = None
        # Consecutive-failure count per _path_key(entity_id, fingerprint),
        # purely in-memory (not persisted across restarts, same as `.data`
        # - see README "A Home Assistant restart resets both sensors").
        # Only ever incremented/reset here in _async_process_trigger and
        # via reset(); never written to directly from __init__.py, unlike
        # `.data` (kept encapsulated since the reset service needs to
        # touch both together - see reset()).
        self._streaks: dict[str, int] = {}

    @staticmethod
    def _path_key(entity_id: str, fingerprint: str) -> str:
        """The dict key `.data`/`._streaks` are actually keyed by - see
        class docstring. "::" can't collide with a real entity_id (which
        never contains a colon) or a trigger_fingerprint() result (a
        trace-derived idx/id, or the "manual" sentinel - none of HA's own
        trigger id defaults contain "::")."""
        return f"{entity_id}::{fingerprint}"

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
    def _ignored_error_texts(self) -> list[str]:
        return self._entry.options.get(
            CONF_IGNORED_ERROR_TEXTS, DEFAULT_IGNORED_ERROR_TEXTS
        )

    def _is_ignored_error(self, error_message: str) -> bool:
        """Whether `error_message` contains any of the configured
        free-text filters (CONF_IGNORED_ERROR_TEXTS) - plain substring
        containment, checked fresh on every trigger (same as
        _excluded_labels/_excluded_automations) so an options change
        takes effect on the very next run without a reload."""
        return any(text in error_message for text in self._ignored_error_texts)

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
        tolerantly as the flakiest one among them). Since v0.10.1 the
        streak this is compared against is counted per-trigger, not per
        automation (see path_key in _async_process_trigger / GH #5) - the
        threshold itself still applies to the whole automation regardless
        of which of its triggers is failing, only the counter it's
        compared against changed.

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
        """Clear every tracked failure for `entity_id` (or literally all
        of them, across every automation, with no target) and their
        streak counts together - used by the automation_monitor.reset
        service. Streaks must be cleared alongside `.data`, not left
        behind: otherwise a "reset" automation that had already reached
        its streak threshold would re-flag itself on its very next
        failure instead of needing a fresh streak from zero, silently
        defeating the point of the threshold right after a reset.

        "Every tracked failure for `entity_id`", plural, since v0.10.1
        (GH #5): one automation can now have several independent
        triggers each holding their own tracked failure (see class
        docstring) - the service has no way to target one specific
        trigger, and clearing only one of an automation's several
        entries while leaving others behind would be a surprising half-
        reset. `.data`/`._streaks` share the same `_path_key(entity_id,
        ...)`-prefixed key format, so a simple prefix match finds all of
        them without needing to inspect each entry's `info["entity_id"]`."""
        if entity_id:
            prefix = self._path_key(entity_id, "")
            for key in [k for k in self.data if k.startswith(prefix)]:
                self.data.pop(key, None)
            for key in [k for k in self._streaks if k.startswith(prefix)]:
                self._streaks.pop(key, None)
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

        # Which of entity_id's own triggers caused this particular run
        # (see trigger_fingerprint.py / GH #5) - `.data`/`._streaks` below
        # are keyed by (entity_id, fingerprint) together, not entity_id
        # alone, so a healthy trigger B succeeding can't wipe out a still-
        # broken trigger A's independently-tracked failure just because
        # they happen to share one automation entity.
        path_key = self._path_key(entity_id, trigger_fingerprint(trace))

        script_execution = trace.get("script_execution")
        last_step = trace.get("last_step")
        aborted_step_had_error = self._step_had_error(trace, last_step)

        # A "finished" run can still be hiding a real problem if a step
        # used `continue_on_error: true` to swallow a genuine runtime
        # error - see classification.py module docstring "finished"
        # entry. Only worth scanning every step for this when the run
        # actually finished; for other script_execution values the
        # existing aborted_step_had_error/error-status handling already
        # covers the relevant cases.
        suppressed_error_step = (
            self._find_suppressed_error_step(trace)
            if script_execution == SCRIPT_EXECUTION_FINISHED
            else None
        )

        if is_execution_failure(
            script_execution,
            aborted_step_had_error=aborted_step_had_error,
            finished_run_had_suppressed_error=suppressed_error_step is not None,
        ):
            # suppressed_error_step (not last_step) for the
            # continue_on_error case - the suppressed error isn't
            # necessarily the last step that ran, and last_step would
            # report the automation's actual final step (likely
            # error-free) instead of the one that mattered. Computed here
            # (before the streak/threshold logic below) so the
            # CONF_IGNORED_ERROR_TEXTS check can see the real error text.
            error_step = suppressed_error_step or last_step
            error_message = self._build_error_message(trace, error_step)
            if self._is_ignored_error(error_message):
                # Matches a configured free-text filter - treated as if
                # this run never happened for classification purposes:
                # no streak change, no flag, existing streak/data (if any,
                # from an earlier *different* failure) left untouched.
                return

            # Consecutive failures *of this specific trigger*, not of the
            # automation as a whole (see path_key above) - an unrelated
            # trigger on the same automation succeeding in between no
            # longer resets this count.
            streak = self._streaks.get(path_key, 0) + 1
            self._streaks[path_key] = streak
            threshold = self._effective_streak_threshold(entity_id)
            if streak >= threshold:
                # Refreshed every time this fires, even if already
                # flagged from an earlier failure in the same streak -
                # keeps last_error_time/error_message current rather
                # than frozen at whichever failure first crossed the
                # threshold.
                self.data[path_key] = {
                    "entity_id": entity_id,
                    "name": self._async_get_name(entity_id),
                    "unique_id": self._async_get_unique_id(entity_id),
                    "last_error_time": datetime.now().astimezone().isoformat(),
                    "error_message": error_message,
                    "error_step": error_step or "unknown",
                    "consecutive_failures": streak,
                }
            # else: below threshold - tracked in _streaks, not yet
            # surfaced in .data/the sensor. A threshold of 1 (default)
            # always flags on this branch, same as before this feature
            # existed.
        else:
            # Only this trigger's own streak/entry is cleared - a
            # successful run on trigger B must not clear trigger A's
            # still-tracked failure just because they share entity_id
            # (see path_key above / GH #5).
            self._streaks.pop(path_key, None)
            self.data.pop(path_key, None)

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
    def _find_suppressed_error_step(trace: dict[str, Any]) -> str | None:
        """First step path (trace dict iteration order - insertion
        order, so lexically the order steps actually ran in) whose own
        `error` field is set - used when script_execution == "finished"
        to detect a `continue_on_error: true` step that swallowed a
        genuine runtime error partway through an otherwise-successful
        run (see classification.py module docstring "finished" entry).

        Unlike `_step_had_error` above (which only ever checks
        `last_step`, meaningful for the "aborted" case where the abort
        *is* the last step that ran), a continue_on_error-suppressed
        error is very likely *not* the last step - execution carries on
        past it - so every step has to be checked here. `None` if no
        step has an error set (the run is a genuine, error-free
        success)."""
        for step_path, steps in trace.get("trace", {}).items():
            if steps and steps[-1].get("error") is not None:
                return step_path
        return None

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
