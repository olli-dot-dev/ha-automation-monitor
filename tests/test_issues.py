"""Tests for the pure placeholder-building behind Repairs issues. No Home
Assistant install required.

Loaded directly by file path (not via `custom_components.automation_monitor`)
because that package's __init__.py imports homeassistant, which would
defeat the point of keeping issues.py dependency-free. See
tests/test_classification.py for the same pattern.
"""

import importlib.util
import pathlib
from datetime import datetime

_MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components/automation_monitor/issues.py"
)
_spec = importlib.util.spec_from_file_location("issues", _MODULE_PATH)
_issues = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_issues)

failed_automation_placeholders = _issues.failed_automation_placeholders
linked_entity_placeholders = _issues.linked_entity_placeholders


# --- failed_automation_placeholders -------------------------------------


def test_failed_automation_placeholders_basic_fields():
    info = {
        "entity_id": "automation.a",
        "unique_id": "garden_watering_1234",
        "name": "Garden Watering",
        "error_message": "Unable to find entity switch.garden_pump",
        "error_step": "action/0",
        "last_error_time": "2026-07-19T10:00:00+02:00",
    }
    placeholders = failed_automation_placeholders(info)
    assert placeholders["name"] == "Garden Watering"
    assert placeholders["error_message"] == "Unable to find entity switch.garden_pump"
    assert placeholders["error_step"] == "action/0"


def test_failed_automation_placeholders_editor_link():
    info = {
        "entity_id": "automation.a",
        "unique_id": "some_unique_id",
        "name": "A",
        "error_message": "boom",
        "error_step": "action/0",
        "last_error_time": "t1",
    }
    placeholders = failed_automation_placeholders(info)
    assert placeholders["editor_link"] == "[**A**](/config/automation/edit/some_unique_id)"


def test_failed_automation_placeholders_falls_back_to_entity_settings_link_without_unique_id():
    # Defensive: unique_id missing from the registry lookup for some
    # reason - link to the entity's own settings instead of producing a
    # dead editor link.
    info = {
        "entity_id": "automation.a",
        "unique_id": None,
        "name": "A",
        "error_message": "boom",
        "error_step": "action/0",
        "last_error_time": "t1",
    }
    placeholders = failed_automation_placeholders(info)
    assert placeholders["editor_link"] == "[**A**](/config/entities/entity/automation.a)"


def test_failed_automation_placeholders_formats_timestamp_in_local_time():
    # Deliberately doesn't assert a fixed clock value - that would only
    # pass on a machine whose system timezone happens to match the one
    # baked into the input.
    iso = "2026-07-19T10:00:00+02:00"
    expected = datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    info = {
        "entity_id": "automation.a", "unique_id": "x", "name": "A",
        "error_message": "boom", "error_step": "action/0", "last_error_time": iso,
    }
    assert failed_automation_placeholders(info)["last_error_time"] == expected


def test_failed_automation_placeholders_unparseable_timestamp_falls_back_to_raw():
    info = {
        "entity_id": "automation.a", "unique_id": "x", "name": "A",
        "error_message": "boom", "error_step": "action/0",
        "last_error_time": "not-a-date",
    }
    assert failed_automation_placeholders(info)["last_error_time"] == "not-a-date"


# --- linked_entity_placeholders ------------------------------------------


def test_linked_entity_placeholders_basic_fields_no_sources():
    info = {
        "entity_id": "light.x",
        "name": "Garden Light",
        "unavailable_since": "2026-07-19T10:00:00+02:00",
        "referenced_by_details": [],
    }
    placeholders = linked_entity_placeholders(info)
    assert placeholders["name"] == "Garden Light"
    assert placeholders["entity_id"] == "light.x"
    assert placeholders["used_by"] == "-"


def test_linked_entity_placeholders_links_to_device():
    info = {
        "entity_id": "media_player.x", "name": "X", "unavailable_since": "t1",
        "device_id": "abc123",
    }
    placeholders = linked_entity_placeholders(info)
    assert placeholders["entity_link"] == "[**X**](/config/devices/device/abc123)"


def test_linked_entity_placeholders_falls_back_to_entity_settings_without_device():
    info = {"entity_id": "light.x", "name": "X", "unavailable_since": "t1"}
    placeholders = linked_entity_placeholders(info)
    assert placeholders["entity_link"] == "[**X**](/config/entities/entity/light.x)"


def test_linked_entity_placeholders_formats_timestamp_in_local_time():
    iso = "2026-07-19T10:00:00+02:00"
    expected = datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    info = {"entity_id": "light.x", "name": "X", "unavailable_since": iso}
    assert linked_entity_placeholders(info)["unavailable_since"] == expected


def test_linked_entity_placeholders_unparseable_timestamp_falls_back_to_raw():
    info = {"entity_id": "light.x", "name": "X", "unavailable_since": "not-a-date"}
    assert linked_entity_placeholders(info)["unavailable_since"] == "not-a-date"


def test_linked_entity_placeholders_includes_source_link():
    info = {
        "entity_id": "light.x", "name": "X", "unavailable_since": "t1",
        "referenced_by_details": [
            {"entity_id": "automation.a", "name": "My Automation", "unique_id": "abc123", "domain": "automation"}
        ],
    }
    placeholders = linked_entity_placeholders(info)
    assert placeholders["used_by"] == "[My Automation](/config/automation/edit/abc123)"


def test_linked_entity_placeholders_includes_script_source_link():
    info = {
        "entity_id": "light.x", "name": "X", "unavailable_since": "t1",
        "referenced_by_details": [
            {"entity_id": "script.b", "name": "My Script", "unique_id": "def456", "domain": "script"}
        ],
    }
    placeholders = linked_entity_placeholders(info)
    assert placeholders["used_by"] == "[My Script](/config/script/edit/def456)"


def test_linked_entity_placeholders_multiple_sources_joined_with_comma():
    info = {
        "entity_id": "light.x", "name": "X", "unavailable_since": "t1",
        "referenced_by_details": [
            {"entity_id": "automation.a", "name": "A", "unique_id": "1", "domain": "automation"},
            {"entity_id": "automation.b", "name": "B", "unique_id": "2", "domain": "automation"},
        ],
    }
    placeholders = linked_entity_placeholders(info)
    assert placeholders["used_by"] == (
        "[A](/config/automation/edit/1), [B](/config/automation/edit/2)"
    )


def test_linked_entity_placeholders_source_without_unique_id_is_plain_text():
    # Defensive: no dead link if a source's unique_id couldn't be resolved.
    info = {
        "entity_id": "light.x", "name": "X", "unavailable_since": "t1",
        "referenced_by_details": [
            {"entity_id": "automation.a", "name": "A", "unique_id": None, "domain": "automation"}
        ],
    }
    placeholders = linked_entity_placeholders(info)
    assert placeholders["used_by"] == "A"
