"""Coordinator: listens for automation_triggered events, fetches the
resulting trace, classifies it, and holds the current failed-automations
state. Event-driven, no polling interval.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .classification import is_execution_failure
from .const import DOMAIN, EVENT_AUTOMATION_TRIGGERED

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

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.data: dict[str, dict[str, Any]] = {}
        self._remove_listener: Any = None

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
            self.data[entity_id] = {
                "entity_id": entity_id,
                "name": self._async_get_name(entity_id),
                "unique_id": self._async_get_unique_id(entity_id),
                "last_error_time": datetime.now().astimezone().isoformat(),
                "error_message": self._build_error_message(trace, last_step),
                "error_step": last_step or "unknown",
            }
        else:
            self.data.pop(entity_id, None)

        self.async_set_updated_data(self.data)

    def _async_get_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    def _async_get_unique_id(self, entity_id: str) -> str | None:
        """The automation's config `id:` (stable across renames) - not its
        entity_id's object_id. Used to link straight to the automation
        editor (`/config/automation/edit/<unique_id>`) from the optional
        persistent notification, see notifications.py. `None` if the
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
