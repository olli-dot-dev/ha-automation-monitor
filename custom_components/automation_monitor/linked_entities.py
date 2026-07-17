"""Pure decision logic for the linked-entities-unavailable sensor. No HA
imports - unit tested directly in tests/test_linked_entities.py, same
pattern as classification.py.

The HA-touching half (walking automations/scripts for referenced
entities, resolving device/area targets via the entity/device
registries) lives in linked_entities_coordinator.py, since it can't be
exercised without a running HomeAssistant instance anyway.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Literal

# Mirrors homeassistant.const.STATE_UNAVAILABLE - not imported directly so
# this module stays HA-import-free. `unknown` is deliberately excluded:
# it's often a legitimate state (right after HA restart before an
# entity's first update, a template sensor whose expression legitimately
# evaluates to None, ...), not a signal that a device is broken/offline.
# Treating it as unavailable-like would risk false positives and
# undermine trust in this sensor, the same concern classification.py
# already documents for the other sensor.
UNAVAILABLE_LIKE_STATES = frozenset({"unavailable"})

TransitionAction = Literal["start", "cancel", "noop"]


def build_reference_map(source_entities: dict[str, Iterable[str]]) -> dict[str, list[str]]:
    """Pure inversion/merge: {source_id: {referenced ids}} ->
    {referenced_id: [source_ids]}, sorted for stable output.
    """
    reference_map: dict[str, set[str]] = {}
    for source_id, referenced_ids in source_entities.items():
        for referenced_id in referenced_ids:
            reference_map.setdefault(referenced_id, set()).add(source_id)
    return {
        referenced_id: sorted(source_ids)
        for referenced_id, source_ids in reference_map.items()
    }


def decide_transition(
    old_state: str | None,
    new_state: str | None,
    unavailable_like: frozenset[str] = UNAVAILABLE_LIKE_STATES,
) -> TransitionAction:
    """Decide what a tracked entity's state-change means for its
    unavailability timer.

    Critical: `async_track_state_change_event` fires on attribute-only
    updates too, where the state string itself is unchanged. Returning
    "noop" whenever old_state == new_state is what stops an unavailable
    entity emitting periodic attribute noise from having its clock reset
    forever and never getting flagged.
    """
    if old_state == new_state:
        return "noop"

    new_is_unavailable = new_state in unavailable_like
    old_was_unavailable = old_state in unavailable_like

    if new_is_unavailable and not old_was_unavailable:
        return "start"
    if not new_is_unavailable and old_was_unavailable:
        return "cancel"
    # Both old and new are unavailable-like but the string differs (only
    # reachable once unavailable_like has more than one member) - still
    # broken, don't reset the clock.
    return "noop"


def time_remaining_until_flag(
    unavailable_since: datetime, now: datetime, threshold_minutes: int
) -> timedelta:
    """How much longer an already-unavailable entity must stay that way
    before it gets flagged, given it's been unavailable since
    `unavailable_since`. Used both for a fresh transition (elapsed == 0)
    and for an entity discovered already-unavailable at startup/rebuild
    time (elapsed may already exceed the threshold, in which case this
    returns timedelta(0) - flag it immediately instead of restarting the
    full threshold).
    """
    elapsed = now - unavailable_since
    remaining = timedelta(minutes=threshold_minutes) - elapsed
    return max(timedelta(0), remaining)
