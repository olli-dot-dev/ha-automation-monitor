"""Pure classification logic: real runtime failure vs. intended stop behaviour.

Deliberately kept free of Home Assistant imports so this - the most
safety-critical part of the integration - can be unit tested without a
running HA instance. False positives here erode user trust in the whole
sensor, so keep the failure set narrow rather than guessing at edge cases.

Values verified against the actual Home Assistant 2026.7.1 source
(homeassistant/helpers/script.py, homeassistant/helpers/trace.py,
homeassistant/components/automation/__init__.py) AND against a live test
instance - not a documented public API, re-verify against real traces if a
HA update changes this:

- "error": an action raised an unhandled exception. Always a failure.
- "aborted": overloaded - set both when a `condition:` *action* mid-
  sequence isn't met (intended) AND when a `stop:` action has
  `error: true`, or on a handful of other internal aborts (real
  problems). Both cases report the same `last_step` path shape (e.g.
  "action/0") - a first attempt at telling them apart via the path
  string was WRONG and misclassified a failed condition action as a
  failure (caught via a live test run, see README). The reliable signal
  instead lives one level deeper: HA explicitly clears the trace step's
  own error on a condition-fail (`trace_element.set_error(None)`) but
  sets it on every other abort (`trace_element.set_error(ex)`). That's
  only visible in the *extended* trace dict's per-step data, not the
  short dict - see `aborted_step_had_error` param.
- "cancelled": e.g. `mode: single` re-triggered while already running.
  Concurrency behaviour, not an error.
- "finished": completed normally (this is what a plain "success" run
  reports - HA does not use the literal string "success").
- "failed_single" / "failed_max_runs": a run was rejected because of the
  automation's `mode:` limits. Same category as "cancelled" - expected
  concurrency behaviour, not an error.
- "failed_conditions": the automation's top-level `condition:` block (as
  opposed to a `condition:` *action*) wasn't met. In practice this value
  never reaches this function - Home Assistant doesn't fire
  `automation_triggered` at all when the top-level condition blocks a
  run, so the coordinator never sees a trace for it. Listed here only
  for defensive completeness.
- "disallowed_recursion_detected": the automation triggered itself
  recursively past HA's safety limit. Treated as a real failure - it
  indicates broken automation logic, not intended behaviour.
"""

from __future__ import annotations

SCRIPT_EXECUTION_ERROR = "error"
SCRIPT_EXECUTION_ABORTED = "aborted"
SCRIPT_EXECUTION_CANCELLED = "cancelled"
SCRIPT_EXECUTION_FINISHED = "finished"
SCRIPT_EXECUTION_FAILED_SINGLE = "failed_single"
SCRIPT_EXECUTION_FAILED_MAX_RUNS = "failed_max_runs"
SCRIPT_EXECUTION_FAILED_CONDITIONS = "failed_conditions"
SCRIPT_EXECUTION_DISALLOWED_RECURSION = "disallowed_recursion_detected"

_ALWAYS_FAILURE = {SCRIPT_EXECUTION_ERROR, SCRIPT_EXECUTION_DISALLOWED_RECURSION}
_NEVER_FAILURE = {
    SCRIPT_EXECUTION_CANCELLED,
    SCRIPT_EXECUTION_FINISHED,
    SCRIPT_EXECUTION_FAILED_SINGLE,
    SCRIPT_EXECUTION_FAILED_MAX_RUNS,
    SCRIPT_EXECUTION_FAILED_CONDITIONS,
}


def is_execution_failure(script_execution: str | None, *, aborted_step_had_error: bool = False) -> bool:
    """Return True if a trace result counts as a real runtime failure.

    `aborted_step_had_error` only matters when `script_execution` is
    "aborted" (see module docstring): pass whether the last executed
    trace step's own `error` field was set, taken from the *extended*
    trace dict (`trace["trace"][last_step][-1].get("error")` is not
    None) - the short trace dict alone can't distinguish the two
    "aborted" cases. Defaults to False (not a failure) so a caller that
    can't determine this doesn't produce a false positive.
    """
    if script_execution in _ALWAYS_FAILURE:
        return True
    if script_execution in _NEVER_FAILURE:
        return False
    if script_execution == SCRIPT_EXECUTION_ABORTED:
        return aborted_step_had_error
    # Unrecognised status (e.g. a future HA version added a new one):
    # default to "not a failure" to avoid false positives.
    return False
