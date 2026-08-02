"""Describe Automation Monitor's Logbook events (Settings -> Logbook) -
same pattern as HA core's own automation integration
(homeassistant/components/automation/logbook.py). Events themselves are
fired in __init__.py, once per flag/resolve *transition* (see
EVENT_FAILURE_DETECTED etc. in const.py).

No manifest.json dependency declaration needed: confirmed against HA core
source that the automation integration's own logbook.py isn't listed in
its manifest's after_dependencies either - the logbook component discovers
every loaded integration's logbook.py platform automatically.

Message text is plain, untranslated English, same as `error_message`
throughout this project (see issues.py module docstring) - it's built at
runtime, not something strings.json's static-form translation mechanism
covers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
    LazyEventPartialState,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_NAME
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_FAILURE_DETECTED,
    EVENT_FAILURE_RESOLVED,
    EVENT_LINKED_ENTITY_AVAILABLE,
    EVENT_LINKED_ENTITY_UNAVAILABLE,
)


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[LazyEventPartialState], dict[str, Any]]], None
    ],
) -> None:
    """Describe logbook events."""

    @callback
    def describe_failure_detected(event: LazyEventPartialState) -> dict[str, Any]:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: data.get(ATTR_NAME),
            LOGBOOK_ENTRY_MESSAGE: f"failed: {data.get('error_message', 'unknown error')}",
            LOGBOOK_ENTRY_ENTITY_ID: data.get(ATTR_ENTITY_ID),
        }

    @callback
    def describe_failure_resolved(event: LazyEventPartialState) -> dict[str, Any]:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: data.get(ATTR_NAME),
            LOGBOOK_ENTRY_MESSAGE: "recovered",
            LOGBOOK_ENTRY_ENTITY_ID: data.get(ATTR_ENTITY_ID),
        }

    @callback
    def describe_linked_entity_unavailable(
        event: LazyEventPartialState,
    ) -> dict[str, Any]:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: data.get(ATTR_NAME),
            LOGBOOK_ENTRY_MESSAGE: (
                "became unavailable (referenced by an automation/script/scene)"
            ),
            LOGBOOK_ENTRY_ENTITY_ID: data.get(ATTR_ENTITY_ID),
        }

    @callback
    def describe_linked_entity_available(
        event: LazyEventPartialState,
    ) -> dict[str, Any]:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: data.get(ATTR_NAME),
            LOGBOOK_ENTRY_MESSAGE: "became available again",
            LOGBOOK_ENTRY_ENTITY_ID: data.get(ATTR_ENTITY_ID),
        }

    async_describe_event(DOMAIN, EVENT_FAILURE_DETECTED, describe_failure_detected)
    async_describe_event(DOMAIN, EVENT_FAILURE_RESOLVED, describe_failure_resolved)
    async_describe_event(
        DOMAIN, EVENT_LINKED_ENTITY_UNAVAILABLE, describe_linked_entity_unavailable
    )
    async_describe_event(
        DOMAIN, EVENT_LINKED_ENTITY_AVAILABLE, describe_linked_entity_available
    )
