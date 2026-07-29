"""Pure placeholder-building for Repairs issues (Settings -> Repairs,
admin-only). No HA imports - unit tested directly in
tests/test_issues.py, same pattern as classification.py /
linked_entities.py.

One issue per currently-failed automation / currently-unavailable linked
entity, not one combined blob - matches how HA's Repairs page already
presents multiple issues as separate, individually-dismissible rows.
Title/description templates with {placeholder} interpolation live in
strings.json (the "issues" section), which go through HA's own
translation system (strings.json + translations/<lang>.json) exactly
like entity names and the Options dialog - unlike the persistent
notifications this replaced, which couldn't use that system at all (free
-form text built at runtime isn't something strings.json's static-form
mechanism covers) and needed a hand-rolled per-language string table
instead. That whole table is gone; only English placeholder *values* are
built here (names, formatted timestamps, markdown links), and
strings.json's translated template text does the rest.

The HA-touching half (issue_registry.async_create_issue/
async_delete_issue, wiring up coordinator listeners) lives in
__init__.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# HA config editor path segment per source domain - automations,
# scripts, and scenes can all appear in a linked entity's referenced_by
# (see linked_entities_coordinator.py), but keyed by domain rather than
# hardcoded to "automation" so a script/scene source still gets a real
# editor link instead of falling back to plain text. The scene route
# follows the same `/config/<domain>/edit/<id>` pattern as
# automation/script - not independently verified live yet, unlike that
# pattern for automation/script.
_EDITOR_PATH_BY_DOMAIN = {"automation": "automation", "script": "script", "scene": "scene"}


def _format_timestamp(iso_string: str) -> str:
    """Human-readable "YYYY-MM-DD HH:MM" in the *local* timezone, instead
    of the raw ISO-8601 string it's built from. Falls back to the raw
    string if it can't be parsed - a formatting nicety failing shouldn't
    take the whole issue down with it.

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
    linked_entity_placeholders actually uses.

    NOT independently verified live yet (unlike most of this project's
    other internal-route assumptions) - `/config/entities/entity/<id>` is
    this project's best understanding of HA's entity-settings deep link,
    not confirmed against a running instance."""
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


def failed_automation_placeholders(info: dict[str, Any]) -> dict[str, str]:
    """Translation placeholders for one failed-automation issue - see
    strings.json "issues.failed_automation" for the template that uses
    them. `error_message` itself is never translated - it's HA's/the
    failing integration's own error text, passed through verbatim (see
    coordinator.py), not something this project can meaningfully
    translate."""
    return {
        "editor_link": _automation_editor_link(
            info.get("unique_id"), info["entity_id"], info["name"]
        ),
        "name": info["name"],
        "error_message": info["error_message"],
        "error_step": info["error_step"],
        "last_error_time": _format_timestamp(info["last_error_time"]),
    }


def linked_entity_placeholders(info: dict[str, Any]) -> dict[str, str]:
    """Translation placeholders for one unavailable-linked-entity issue -
    see strings.json "issues.linked_entity_unavailable" for the template
    that uses them."""
    sources = info.get("referenced_by_details") or []
    used_by = ", ".join(_source_link(source) for source in sources) if sources else "-"
    return {
        "entity_link": _device_or_entity_link(
            info["entity_id"], info["name"], info.get("device_id")
        ),
        "entity_id": info["entity_id"],
        "name": info["name"],
        "unavailable_since": _format_timestamp(info["unavailable_since"]),
        "used_by": used_by,
    }
