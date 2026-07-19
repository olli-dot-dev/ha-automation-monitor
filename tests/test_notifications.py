"""Tests for the pure message-building behind the optional persistent
notifications. No Home Assistant install required.

Loaded directly by file path (not via `custom_components.automation_monitor`)
because that package's __init__.py imports homeassistant, which would
defeat the point of keeping notifications.py dependency-free. See
tests/test_classification.py for the same pattern.
"""

import importlib.util
import pathlib

_MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components/automation_monitor/notifications.py"
)
_spec = importlib.util.spec_from_file_location("notifications", _MODULE_PATH)
_notifications = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_notifications)

build_failed_automations_message = _notifications.build_failed_automations_message
build_linked_entities_message = _notifications.build_linked_entities_message


# --- build_failed_automations_message ---------------------------------


def test_build_failed_automations_message_empty_data_is_empty_string():
    assert build_failed_automations_message({}) == ""


def test_build_failed_automations_message_single_entry():
    data = {
        "automation.a": {
            "entity_id": "automation.a",
            "unique_id": "garden_watering_1234",
            "name": "Garden Watering",
            "error_message": "Unable to find entity switch.garden_pump",
        }
    }
    assert build_failed_automations_message(data) == (
        "- [**Garden Watering**](/config/automation/edit/garden_watering_1234): "
        "Unable to find entity switch.garden_pump"
    )


def test_build_failed_automations_message_sorted_by_name():
    # Order must not depend on dict/insertion order - stable, readable
    # output regardless of which one failed first.
    data = {
        "automation.b": {
            "entity_id": "automation.b", "unique_id": "b", "name": "Zzz Automation",
            "error_message": "boom",
        },
        "automation.a": {
            "entity_id": "automation.a", "unique_id": "a", "name": "Aaa Automation",
            "error_message": "bang",
        },
    }
    message = build_failed_automations_message(data)
    assert message.index("Aaa Automation") < message.index("Zzz Automation")


def test_build_failed_automations_message_links_to_automation_editor():
    data = {
        "automation.a": {
            "entity_id": "automation.a", "unique_id": "some_unique_id", "name": "A",
            "error_message": "boom",
        }
    }
    message = build_failed_automations_message(data)
    assert "[**A**](/config/automation/edit/some_unique_id)" in message


def test_build_failed_automations_message_falls_back_to_entity_settings_link_without_unique_id():
    # Defensive: unique_id missing from the registry lookup for some
    # reason - link to the entity's own settings instead of producing a
    # dead editor link.
    data = {
        "automation.a": {
            "entity_id": "automation.a", "unique_id": None, "name": "A",
            "error_message": "boom",
        }
    }
    message = build_failed_automations_message(data)
    assert "[**A**](/config/entities/entity/automation.a)" in message


# --- build_linked_entities_message -------------------------------------


def test_build_linked_entities_message_empty_data_is_empty_string():
    assert build_linked_entities_message({}) == ""


def test_build_linked_entities_message_single_entry_no_sources():
    # Timestamp isn't asserted as a fixed clock value here - see
    # test_build_linked_entities_message_formats_timestamp_in_local_time
    # for why (local-time conversion, not the raw stored UTC value; even
    # the date, not just the time, can shift depending on the system
    # timezone the test happens to run under).
    from datetime import datetime as _datetime

    iso = "2026-07-19T10:00:00+02:00"
    expected_ts = _datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")

    data = {
        "light.x": {
            "entity_id": "light.x",
            "name": "Garden Light",
            "unavailable_since": iso,
            "referenced_by_details": [],
        }
    }
    assert build_linked_entities_message(data).startswith(
        f"- [**Garden Light**](/config/entities/entity/light.x) (`light.x`) "
        f"unavailable since {expected_ts}"
    )


def test_build_linked_entities_message_sorted_by_name():
    data = {
        "light.b": {"entity_id": "light.b", "name": "Zzz Light", "unavailable_since": "t1"},
        "light.a": {"entity_id": "light.a", "name": "Aaa Light", "unavailable_since": "t2"},
    }
    message = build_linked_entities_message(data)
    assert message.index("Aaa Light") < message.index("Zzz Light")


def test_build_linked_entities_message_links_to_device():
    data = {
        "media_player.x": {
            "entity_id": "media_player.x", "name": "X", "unavailable_since": "t1",
            "device_id": "abc123",
        }
    }
    message = build_linked_entities_message(data)
    assert "[**X**](/config/devices/device/abc123)" in message


def test_build_linked_entities_message_falls_back_to_entity_settings_without_device():
    # No device_id (helper/template entity, or the field is simply
    # missing) - link to entity settings instead of a dead device link.
    data = {
        "light.x": {
            "entity_id": "light.x", "name": "X", "unavailable_since": "t1",
        }
    }
    message = build_linked_entities_message(data)
    assert "[**X**](/config/entities/entity/light.x)" in message


def test_build_linked_entities_message_formats_timestamp_in_local_time():
    # Deliberately doesn't assert a fixed clock value - that would only
    # pass on a machine whose system timezone happens to match the one
    # baked into the input, which isn't true in CI/other dev machines.
    # Instead checks it actually went through the same local-time
    # conversion the implementation uses (see notifications.py
    # docstring), not just stripped-down raw UTC.
    from datetime import datetime as _datetime

    iso = "2026-07-19T10:00:00+02:00"
    expected = _datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")

    data = {"light.x": {"entity_id": "light.x", "name": "X", "unavailable_since": iso}}
    message = build_linked_entities_message(data)
    assert f"unavailable since {expected}" in message
    assert "T10:00:00" not in message


def test_build_linked_entities_message_unparseable_timestamp_falls_back_to_raw():
    data = {
        "light.x": {"entity_id": "light.x", "name": "X", "unavailable_since": "not-a-date"}
    }
    message = build_linked_entities_message(data)
    assert "unavailable since not-a-date" in message


def test_build_linked_entities_message_includes_source_link():
    data = {
        "light.x": {
            "entity_id": "light.x",
            "name": "X",
            "unavailable_since": "t1",
            "referenced_by_details": [
                {
                    "entity_id": "automation.a",
                    "name": "My Automation",
                    "unique_id": "abc123",
                    "domain": "automation",
                }
            ],
        }
    }
    message = build_linked_entities_message(data)
    assert "used by [My Automation](/config/automation/edit/abc123)" in message


def test_build_linked_entities_message_includes_script_source_link():
    data = {
        "light.x": {
            "entity_id": "light.x",
            "name": "X",
            "unavailable_since": "t1",
            "referenced_by_details": [
                {
                    "entity_id": "script.b",
                    "name": "My Script",
                    "unique_id": "def456",
                    "domain": "script",
                }
            ],
        }
    }
    message = build_linked_entities_message(data)
    assert "used by [My Script](/config/script/edit/def456)" in message


def test_build_linked_entities_message_multiple_sources_joined_with_comma():
    data = {
        "light.x": {
            "entity_id": "light.x",
            "name": "X",
            "unavailable_since": "t1",
            "referenced_by_details": [
                {"entity_id": "automation.a", "name": "A", "unique_id": "1", "domain": "automation"},
                {"entity_id": "automation.b", "name": "B", "unique_id": "2", "domain": "automation"},
            ],
        }
    }
    message = build_linked_entities_message(data)
    assert (
        "used by [A](/config/automation/edit/1), [B](/config/automation/edit/2)"
        in message
    )


def test_build_linked_entities_message_source_without_unique_id_is_plain_text():
    # Defensive: no dead link if a source's unique_id couldn't be resolved.
    data = {
        "light.x": {
            "entity_id": "light.x",
            "name": "X",
            "unavailable_since": "t1",
            "referenced_by_details": [
                {"entity_id": "automation.a", "name": "A", "unique_id": None, "domain": "automation"}
            ],
        }
    }
    message = build_linked_entities_message(data)
    assert "used by A" in message
    assert "(/config/automation/edit/" not in message


def test_build_linked_entities_message_includes_settings_link_when_nonempty():
    data = {
        "light.x": {"entity_id": "light.x", "name": "X", "unavailable_since": "t1"}
    }
    message = build_linked_entities_message(data)
    assert "[Automation Monitor settings](/config/integrations/integration/automation_monitor)" in message


def test_build_linked_entities_message_empty_data_has_no_settings_link():
    # Empty data must still produce an empty string overall (caller relies
    # on this to decide whether to dismiss the notification) - the
    # settings link must not sneak in on its own.
    assert build_linked_entities_message({}) == ""


def test_build_linked_entities_message_includes_copy_hint_when_nonempty():
    data = {
        "light.x": {"entity_id": "light.x", "name": "X", "unavailable_since": "t1"}
    }
    message = build_linked_entities_message(data)
    assert "copy its entity_id above" in message


def test_build_linked_entities_message_shows_entity_id_as_inline_code():
    data = {
        "media_player.x": {
            "entity_id": "media_player.x", "name": "X", "unavailable_since": "t1",
        }
    }
    message = build_linked_entities_message(data)
    assert "(`media_player.x`)" in message
