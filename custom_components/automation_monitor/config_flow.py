"""Config flow for Automation Monitor.

Single-instance. Options flow added for the linked-entities-unavailable
sensor's threshold (see linked_entities_coordinator.py) - the "no options
needed for MVP" state this docstring used to describe is what this is the
later addition to.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback

from .const import (
    CONF_UNAVAILABLE_THRESHOLD_MINUTES,
    DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES,
    DOMAIN,
)


class AutomationMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Automation Monitor."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Automation Monitor", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AutomationMonitorOptionsFlow:
        return AutomationMonitorOptionsFlow()


class AutomationMonitorOptionsFlow(config_entries.OptionsFlow):
    """Single field: how many minutes a linked entity must stay
    continuously unavailable before it's flagged.

    Deliberately does NOT set self.config_entry in an __init__ override -
    relies on the base class's own `config_entry` property, which current
    HA versions populate automatically (manually assigning it is
    deprecated/rejected on newer HA). Verified against the project's
    target 2026.7.1 during live testing - re-check if this integration is
    ever run against a materially older HA version.
    """

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_UNAVAILABLE_THRESHOLD_MINUTES, DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UNAVAILABLE_THRESHOLD_MINUTES, default=current
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
