"""Config flow for Automation Monitor.

Single-instance, no options needed for MVP (a "postpone" setting for slow
systems, analogous to Watchman, may be added later - see README roadmap).
"""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class AutomationMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Automation Monitor."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Automation Monitor", data={})

        return self.async_show_form(step_id="user")
