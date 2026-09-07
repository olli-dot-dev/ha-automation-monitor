"""Tests for the pure trigger-identification logic behind GH #5 (a
consolidated automation with several independent triggers, where one
succeeding wrongly cleared another's still-tracked failure). No Home
Assistant install required.

Loaded directly by file path (not via `custom_components.automation_monitor`)
because that package's __init__.py imports homeassistant, which would
defeat the point of keeping trigger_fingerprint.py dependency-free. See
tests/test_classification.py for the same pattern.

Trace shapes below mirror what was actually observed against a live HA
2026.7.4 instance (see trigger_fingerprint.py module docstring) - trimmed
to only the fields trigger_fingerprint() reads.
"""

import importlib.util
import pathlib

_MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components/automation_monitor/trigger_fingerprint.py"
)
_spec = importlib.util.spec_from_file_location("trigger_fingerprint", _MODULE_PATH)
_trigger_fingerprint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_trigger_fingerprint)

trigger_fingerprint = _trigger_fingerprint.trigger_fingerprint
MANUAL_TRIGGER_FINGERPRINT = _trigger_fingerprint.MANUAL_TRIGGER_FINGERPRINT


def _trace_for_trigger_idx(idx, explicit_id=None):
    return {
        "trace": {
            f"trigger/{idx}": [
                {
                    "changed_variables": {
                        "trigger": {"id": explicit_id or idx, "idx": idx},
                    },
                },
            ],
            "action/0": [{"changed_variables": {}}],
        },
    }


def test_first_configured_trigger_gets_its_own_fingerprint():
    assert trigger_fingerprint(_trace_for_trigger_idx("0")) == "0"


def test_second_configured_trigger_gets_a_different_fingerprint():
    assert trigger_fingerprint(_trace_for_trigger_idx("1")) == "1"


def test_two_different_triggers_produce_different_fingerprints():
    # The actual bug from GH #5: these two must NOT collide, or a
    # successful run on one clears the other's still-tracked failure.
    a = trigger_fingerprint(_trace_for_trigger_idx("0"))
    b = trigger_fingerprint(_trace_for_trigger_idx("1"))
    assert a != b


def test_repeated_runs_of_the_same_trigger_produce_the_same_fingerprint():
    first = trigger_fingerprint(_trace_for_trigger_idx("0"))
    second = trigger_fingerprint(_trace_for_trigger_idx("0"))
    assert first == second


def test_explicit_user_set_trigger_id_is_used_verbatim():
    trace = _trace_for_trigger_idx("0", explicit_id="presence_trigger")
    assert trigger_fingerprint(trace) == "presence_trigger"


def test_two_trigger_configs_sharing_one_explicit_id_collapse_to_one_fingerprint():
    # Documented HA pattern: several trigger: entries can share one user-set
    # id: to be treated as one logical trigger - intentional, not a bug.
    trace_a = _trace_for_trigger_idx("0", explicit_id="shared")
    trace_b = _trace_for_trigger_idx("2", explicit_id="shared")
    assert trigger_fingerprint(trace_a) == trigger_fingerprint(trace_b)


def test_manually_triggered_run_falls_back_to_the_manual_sentinel():
    # automation.trigger service / "Run actions" in the UI: no "trigger/N"
    # step at all, just a bare "trigger" step with no usable trigger info.
    trace = {"trace": {"trigger": [{"changed_variables": {}}], "action/0": [{}]}}
    assert trigger_fingerprint(trace) == MANUAL_TRIGGER_FINGERPRINT


def test_missing_trigger_step_entirely_falls_back_to_the_manual_sentinel():
    trace = {"trace": {"action/0": [{"changed_variables": {}}]}}
    assert trigger_fingerprint(trace) == MANUAL_TRIGGER_FINGERPRINT


def test_missing_trace_key_falls_back_to_the_manual_sentinel():
    assert trigger_fingerprint({}) == MANUAL_TRIGGER_FINGERPRINT
