"""Tests for the pure decision logic behind the linked-entities-unavailable
sensor. No Home Assistant install required.

Loaded directly by file path (not via `custom_components.automation_monitor`)
because that package's __init__.py imports homeassistant, which would
defeat the point of keeping linked_entities.py dependency-free. See
tests/test_classification.py for the same pattern.
"""

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone

_MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components/automation_monitor/linked_entities.py"
)
_spec = importlib.util.spec_from_file_location("linked_entities", _MODULE_PATH)
_linked_entities = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_linked_entities)

build_reference_map = _linked_entities.build_reference_map
decide_transition = _linked_entities.decide_transition
time_remaining_until_flag = _linked_entities.time_remaining_until_flag
UNAVAILABLE_LIKE_STATES = _linked_entities.UNAVAILABLE_LIKE_STATES


# --- build_reference_map ---------------------------------------------------


def test_build_reference_map_inverts_and_sorts():
    source = {
        "automation.a": {"light.x", "light.y"},
        "script.b": {"light.x"},
    }
    assert build_reference_map(source) == {
        "light.x": ["automation.a", "script.b"],
        "light.y": ["automation.a"],
    }


def test_build_reference_map_empty_input_gives_empty_map():
    assert build_reference_map({}) == {}


def test_build_reference_map_entity_referenced_by_nothing_is_absent():
    # An automation/script with no references at all shouldn't add any key.
    source = {"automation.a": set()}
    assert build_reference_map(source) == {}


def test_build_reference_map_ignored_entity_is_excluded():
    source = {
        "automation.a": {"light.x", "light.y"},
        "script.b": {"light.x"},
    }
    assert build_reference_map(source, ignored={"light.x"}) == {
        "light.y": ["automation.a"],
    }


def test_build_reference_map_ignoring_all_referenced_entities_gives_empty_map():
    source = {"automation.a": {"light.x"}}
    assert build_reference_map(source, ignored={"light.x"}) == {}


def test_build_reference_map_ignored_entity_not_referenced_is_a_noop():
    # Ignoring an entity that isn't referenced by anything shouldn't affect
    # the map's other entries.
    source = {"automation.a": {"light.x"}}
    assert build_reference_map(source, ignored={"light.unrelated"}) == {
        "light.x": ["automation.a"],
    }


def test_build_reference_map_no_ignored_argument_behaves_as_before():
    # Default is an empty iterable, not a required argument - existing
    # callers (and this test file's other tests) must keep working
    # unchanged.
    source = {"automation.a": {"light.x"}}
    assert build_reference_map(source) == {"light.x": ["automation.a"]}


# --- decide_transition -------------------------------------------------


def test_decide_transition_available_to_unavailable_starts():
    assert decide_transition("on", "unavailable") == "start"


def test_decide_transition_unavailable_to_available_cancels():
    assert decide_transition("unavailable", "on") == "cancel"


def test_decide_transition_attribute_only_change_is_noop():
    # Same state string on both sides - e.g. a brightness update while the
    # light stays "on". Must not touch the timer.
    assert decide_transition("on", "on") == "noop"


def test_decide_transition_unavailable_attribute_noise_is_noop():
    # The critical case: an already-unavailable entity emitting periodic
    # attribute-only updates must NOT reset its clock, or it would never
    # get flagged.
    assert decide_transition("unavailable", "unavailable") == "noop"


def test_decide_transition_between_two_available_states_is_noop():
    assert decide_transition("on", "off") == "noop"


def test_decide_transition_none_to_unavailable_starts():
    # Entity just added to the tracked set with no prior known state.
    assert decide_transition(None, "unavailable") == "start"


def test_decide_transition_within_expanded_unavailable_like_set_is_noop():
    # If unavailable_like ever grows beyond {"unavailable"}, a transition
    # between two of its members (e.g. unavailable -> unknown) must not
    # reset the clock - still broken, just differently reported.
    expanded = frozenset({"unavailable", "unknown"})
    assert decide_transition("unavailable", "unknown", expanded) == "noop"


# --- time_remaining_until_flag ------------------------------------------


def test_time_remaining_fresh_transition_is_full_threshold():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    remaining = time_remaining_until_flag(now, now, threshold_minutes=15)
    assert remaining == timedelta(minutes=15)


def test_time_remaining_partway_through_is_reduced():
    since = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = since + timedelta(minutes=5)
    remaining = time_remaining_until_flag(since, now, threshold_minutes=15)
    assert remaining == timedelta(minutes=10)


def test_time_remaining_already_past_threshold_is_zero_not_negative():
    # Discovered already-unavailable at startup/rebuild, long since broken -
    # must flag immediately, not wait out a fresh full threshold.
    since = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = since + timedelta(hours=3)
    remaining = time_remaining_until_flag(since, now, threshold_minutes=15)
    assert remaining == timedelta(0)


def test_time_remaining_exactly_at_threshold_is_zero():
    since = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = since + timedelta(minutes=15)
    remaining = time_remaining_until_flag(since, now, threshold_minutes=15)
    assert remaining == timedelta(0)


# --- UNAVAILABLE_LIKE_STATES ------------------------------------------


def test_unavailable_like_states_excludes_unknown():
    # Explicit scope decision: "unknown" is often legitimate (right after
    # restart, a template with no value yet) and must not be treated as a
    # sign of a broken device.
    assert "unavailable" in UNAVAILABLE_LIKE_STATES
    assert "unknown" not in UNAVAILABLE_LIKE_STATES
