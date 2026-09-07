"""Pure logic for identifying *which* of an automation's configured
triggers caused a given run (GH #5). No HA imports - unit tested directly
in tests/test_trigger_fingerprint.py, same pattern as
classification.py/linked_entities.py/issues.py.

Why this exists: a consolidated automation with several independent
triggers (e.g. one "lighting automation" reacting to presence detectors, a
remote, and the sun's position - a real reported setup) is really several
independent pieces of logic sharing one entity_id. Before this module
existed, coordinator.py tracked exactly one failure state per automation
entity_id: a successful run on trigger B's branch cleared a still-broken
trigger A's branch, simply because both share the same automation entity.
This lets the coordinator key failure state per (entity_id, fingerprint)
pair instead, so independent triggers stop clobbering each other's
tracked state.

Verified against a live HA 2026.7.4 instance (2026-09-07) with a two-
trigger test automation, not a documented public API - re-verify against
real traces if a HA update changes this:

- A normally-fired run's extended trace dict has a step keyed
  "trigger/<idx>" (idx = the trigger's position in the automation's
  `trigger:`/`triggers:` list, as a string), whose `changed_variables`
  contains a "trigger" dict with an "id" field - either the trigger's own
  user-set `id:`, or (when unset) the same string as `idx`. Either way,
  `trigger.id` alone is enough: it already collapses to the position
  index when the user hasn't opted into a custom one, and correctly
  merges several trigger configs that intentionally *share* one user-set
  id - a documented HA pattern for treating multiple trigger configs as
  one logical trigger.
- A manually-triggered run (the `automation.trigger` service, "Run
  actions" in the UI, called from another automation/script, ...) has no
  such step at all - just a bare "trigger" step with no usable
  `changed_variables` trigger info. These fall back to a constant
  sentinel so they all still share one slot with each other, same as this
  integration's original one-slot-per-automation behaviour.

Deliberately does NOT attempt to fingerprint *which* `choose:`/`if:`
branch ran within the action sequence - trigger identity is a much
simpler, more robust signal that already matches the reported real-world
case (independent triggers, not necessarily routed through a `choose:` at
all), without having to handle arbitrarily nested choose/if/parallel/
repeat action trees. Known limitation: two different triggers that both
happen to feed the *same* downstream branch are still tracked as separate
slots - an intentional, safe-by-default over-approximation (never hides a
real, distinct failure) rather than a false negative.
"""

from __future__ import annotations

from typing import Any

MANUAL_TRIGGER_FINGERPRINT = "manual"


def trigger_fingerprint(trace: dict[str, Any]) -> str:
    """Identify which configured trigger produced `trace` (an extended
    automation trace dict, see coordinator.py `_get_last_trace`) - stable
    across repeated runs of the *same* trigger, distinct across different
    ones. Falls back to MANUAL_TRIGGER_FINGERPRINT when the run wasn't
    caused by one of the automation's own triggers (see module
    docstring)."""
    steps = trace.get("trace", {})
    trigger_step_path = next(
        (path for path in steps if path == "trigger" or path.startswith("trigger/")),
        None,
    )
    if trigger_step_path is None:
        return MANUAL_TRIGGER_FINGERPRINT
    for entry in steps[trigger_step_path]:
        trigger_vars = (entry.get("changed_variables") or {}).get("trigger")
        if trigger_vars and trigger_vars.get("id") is not None:
            return str(trigger_vars["id"])
    return MANUAL_TRIGGER_FINGERPRINT
