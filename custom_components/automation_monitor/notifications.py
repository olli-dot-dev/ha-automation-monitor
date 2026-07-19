"""Pure message-building for the optional persistent notifications. No HA
imports - unit tested directly in tests/test_notifications.py, same
pattern as classification.py / linked_entities.py.

The HA-touching half (calling persistent_notification.async_create/
async_dismiss, wiring up coordinator listeners) lives in __init__.py -
kept there rather than a dedicated coordinator-listener file since it's a
thin, stateless reaction to data either coordinator already exposes, not
something that itself needs state/lifecycle management.

One persistent notification per sensor, not per entry: each call rebuilds
the full current-state message and re-creates the notification under a
fixed ID (see const.py), so it always reflects "what's wrong right now" -
the same reflects-current-state philosophy as the sensors themselves,
rather than a growing event log.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# HA config editor path segment per source domain - only automations and
# scripts can ever appear in a linked entity's referenced_by (see
# linked_entities_coordinator.py), but keyed by domain rather than
# hardcoded to "automation" so a script source still gets a real editor
# link instead of falling back to plain text.
_EDITOR_PATH_BY_DOMAIN = {"automation": "automation", "script": "script"}


def _format_timestamp(iso_string: str) -> str:
    """Human-readable "YYYY-MM-DD HH:MM" in the *local* timezone, instead
    of the raw ISO-8601 string (seconds + UTC offset, since
    `unavailable_since` is always stored as a UTC timestamp internally -
    see linked_entities_coordinator.py) it's built from. Falls back to
    the raw string if it can't be parsed - a formatting nicety failing
    shouldn't take the whole notification down with it.

    `.astimezone()` with no argument converts to the *system* local
    timezone rather than HA's own configured `hass.config.time_zone` -
    this module deliberately has no HA imports (see module docstring),
    so it can't read that setting directly. Correct as long as the
    machine's OS timezone matches HA's configured one, which it does for
    a typical single-purpose HAOS install - flagging this rather than
    silently assuming it always holds."""
    try:
        dt = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def _entity_settings_link(entity_id: str, name: str) -> str:
    """Markdown link turning an entity's name into a jump-to-its-settings
    link. Fallback for entities with no device (helpers, template
    entities, ...) - see _device_or_entity_link, which is what
    build_linked_entities_message actually uses.

    NOT independently verified live yet (unlike most of this project's
    other internal-route assumptions) - `/config/entities/entity/<id>` is
    this project's best understanding of HA's entity-settings deep link,
    not confirmed against a running instance. See README Testing notes."""
    return f"[**{name}**](/config/entities/entity/{entity_id})"


def _device_or_entity_link(entity_id: str, name: str, device_id: str | None) -> str:
    """Markdown link to the entity's device page
    (`/config/devices/device/<device_id>`) if it belongs to one - a
    well-established, stable HA route, unlike the entity-settings
    fallback above. Most linked entities worth monitoring (lights,
    switches, media players, ...) come from a physical device; a handful
    of entity types (helpers, template entities, ...) don't have one, so
    still fall back to the entity settings link rather than a dead link."""
    if device_id:
        return f"[**{name}**](/config/devices/device/{device_id})"
    return _entity_settings_link(entity_id, name)


def _automation_editor_link(unique_id: str | None, entity_id: str, name: str) -> str:
    """Markdown link to the automation editor (where you'd actually go to
    fix it), keyed by the automation's config `id:` (unique_id) rather
    than its entity_id - that's what `/config/automation/edit/<id>`
    expects. Falls back to the entity settings link if the unique_id is
    missing for some reason, rather than producing a dead link."""
    if unique_id is None:
        return _entity_settings_link(entity_id, name)
    return f"[**{name}**](/config/automation/edit/{unique_id})"


def _source_link(source: dict[str, Any]) -> str:
    """Markdown link to the editor of one automation/script referencing a
    flagged linked entity (see `referenced_by_details` in
    linked_entities_coordinator.py). Falls back to plain (unlinked) text
    if the domain isn't automation/script or the unique_id couldn't be
    resolved - a missing link is a minor inconvenience, a dead link is
    worse."""
    editor_domain = _EDITOR_PATH_BY_DOMAIN.get(source.get("domain"))
    unique_id = source.get("unique_id")
    if editor_domain and unique_id:
        return f"[{source['name']}](/config/{editor_domain}/edit/{unique_id})"
    return source["name"]


def build_failed_automations_message(data: dict[str, dict[str, Any]]) -> str:
    """One line per currently-failed automation. Empty string if `data` is
    empty - caller is expected to dismiss the notification in that case
    rather than show an empty one."""
    lines = [
        f"- {_automation_editor_link(info.get('unique_id'), info['entity_id'], info['name'])}: "
        f"{info['error_message']}"
        for info in sorted(data.values(), key=lambda info: info["name"])
    ]
    return "\n".join(lines)


def build_linked_entities_message(data: dict[str, dict[str, Any]]) -> str:
    """One line per currently-unavailable linked entity: a link to its
    device (or its own settings, if it has no device), when it went
    unavailable, and - if known - which automation(s)/script(s) actually
    reference it, each linking straight to its editor. Empty string if
    `data` is empty - same convention as build_failed_automations_message."""
    lines = []
    for info in sorted(data.values(), key=lambda info: info["name"]):
        link = _device_or_entity_link(info["entity_id"], info["name"], info.get("device_id"))
        line = f"- {link} unavailable since {_format_timestamp(info['unavailable_since'])}"
        sources = info.get("referenced_by_details") or []
        if sources:
            line += " · used by " + ", ".join(_source_link(s) for s in sources)
        lines.append(line)
    return "\n".join(lines)
