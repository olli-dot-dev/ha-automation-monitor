"""Tests for the core classification rule - the most safety-critical part
of the integration. No Home Assistant install required.

Loaded directly by file path (not via `custom_components.automation_monitor`)
because that package's __init__.py imports homeassistant, which would
defeat the point of keeping classification.py dependency-free.
"""

import importlib.util
import pathlib

_MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components/automation_monitor/classification.py"
)
_spec = importlib.util.spec_from_file_location("classification", _MODULE_PATH)
_classification = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_classification)

is_execution_failure = _classification.is_execution_failure


def test_error_is_a_failure():
    assert is_execution_failure("error") is True


def test_disallowed_recursion_is_a_failure():
    assert is_execution_failure("disallowed_recursion_detected") is True


def test_aborted_by_mid_sequence_condition_action_is_not_a_failure():
    # HA explicitly clears the step's own error on a condition-fail.
    assert is_execution_failure("aborted", aborted_step_had_error=False) is False


def test_aborted_by_stop_action_with_error_true_is_a_failure():
    # HA sets the step's own error for every other abort, e.g. `stop: ... error: true`.
    assert is_execution_failure("aborted", aborted_step_had_error=True) is True


def test_aborted_without_step_error_info_defaults_to_not_a_failure():
    # Caller couldn't determine step error info - default to no false positive.
    assert is_execution_failure("aborted") is False


def test_cancelled_by_mode_single_is_not_a_failure():
    assert is_execution_failure("cancelled") is False


def test_failed_single_is_not_a_failure():
    assert is_execution_failure("failed_single") is False


def test_failed_max_runs_is_not_a_failure():
    assert is_execution_failure("failed_max_runs") is False


def test_failed_conditions_is_not_a_failure():
    # Defensive only - HA never fires automation_triggered for this case,
    # so this value should never actually reach the classifier.
    assert is_execution_failure("failed_conditions") is False


def test_finished_is_not_a_failure():
    assert is_execution_failure("finished") is False


def test_unknown_status_defaults_to_not_a_failure():
    assert is_execution_failure("something_new_in_a_future_ha_version") is False
