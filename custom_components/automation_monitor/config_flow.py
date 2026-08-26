"""Config flow for Automation Monitor.

Single-instance. Options flow added for the linked-entities-unavailable
sensor's threshold and ignore-list (see linked_entities_coordinator.py),
plus a Repairs-issue toggle per sensor (see issues.py) - the "no options
needed for MVP" state this docstring used to describe is what this is
the later addition to.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENTITY_STREAK_OVERRIDES,
    CONF_EXCLUDE_OFF_AUTOMATIONS,
    CONF_EXCLUDED_AUTOMATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_FAILURE_STREAK_THRESHOLD,
    CONF_IGNORED_ENTITIES,
    CONF_IGNORED_ERROR_TEXTS,
    CONF_NOTIFY_FAILED_AUTOMATIONS,
    CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE,
    CONF_UNAVAILABLE_THRESHOLD_MINUTES,
    DEFAULT_ENTITY_STREAK_OVERRIDES,
    DEFAULT_EXCLUDE_OFF_AUTOMATIONS,
    DEFAULT_EXCLUDED_AUTOMATIONS,
    DEFAULT_EXCLUDED_LABELS,
    DEFAULT_FAILURE_STREAK_THRESHOLD,
    DEFAULT_IGNORED_ENTITIES,
    DEFAULT_IGNORED_ERROR_TEXTS,
    DEFAULT_NOTIFY,
    DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES,
    DOMAIN,
    EXCLUSION_SCOPES,
)

# Selection-only field names used in step "init" to pick which entities get
# a row in step "overrides" - never written into the config entry's options
# themselves, only used to build that step's schema (see _finish, which
# strips them back out).
_STREAK_OVERRIDE_SELECT = "streak_override_entities"
_EXCLUDED_AUTOMATIONS_SELECT = "excluded_automations_entities"


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
    """Menu-based: step "init" is a menu (not a form) offering three fully
    independent entry points, grouped by *what* they configure rather
    than by feature -

    - "general": settings that aren't clearly entity- or
      automation-specific (unavailable threshold, excluded labels - which
      affect both automations AND entities/devices, so can't live in
      either of the other two groups - both notification toggles, the
      global failure-streak-threshold default, the ignored-error-texts
      free-text filter list).
    - "entities" -> "streak_overrides": entity-level settings - the
      linked-entities ignore list (CONF_IGNORED_ENTITIES) plus per-entity
      streak-threshold overrides (CONF_ENTITY_STREAK_OVERRIDES). The
      first is a plain field on "entities" itself; the second needs a
      second screen ("streak_overrides") since HA's selectors have no
      single widget for "entity + number" - "entities" only lets the
      user *pick* which entities need their own threshold, and
      "streak_overrides" dynamically builds one number field per picked
      entity.
    - "automations" -> "automation_exclusions": automation-level
      settings - the skip-turned-off-automations toggle
      (CONF_EXCLUDE_OFF_AUTOMATIONS) plus per-automation per-sensor
      exclusion (CONF_EXCLUDED_AUTOMATIONS), same plain-field-plus-second
      -screen shape as "entities" above.

    CONF_IGNORED_ENTITIES and CONF_EXCLUDE_OFF_AUTOMATIONS used to live on
    "general" (this flow's original single-step form covered everything);
    moved into the "entities"/"automations" groups they actually belong
    to once those groups existed, rather than leaving "general" as a
    catch-all for anything that predates the newer per-entity/per
    -automation features.

    Reachable independently via the menu specifically so tweaking one
    setting doesn't require re-submitting the others too (an earlier,
    linear version of this flow needed that). Every branch's _finish_*
    method merges its changes into a copy of self.config_entry.options
    (not `self._pending_*`/a fresh dict) - each branch only ever
    holds/submits *some* of the option keys, so building the saved data
    from anything other than the full current option set would silently
    wipe whatever the other branches own. This is the same failure shape
    as the stale-notification bug fixed in v0.7.2 (options save
    resetting state nothing asked to touch) - worth remembering if this
    flow is restructured again.

    Deliberately does NOT set self.config_entry in an __init__ override -
    relies on the base class's own `config_entry` property, which current
    HA versions populate automatically (manually assigning it is
    deprecated/rejected on newer HA). Verified against the project's
    target 2026.7.1 during live testing - re-check if this integration is
    ever run against a materially older HA version.
    """

    def __init__(self) -> None:
        # field_key -> entity_id maps built by async_step_streak_overrides /
        # async_step_automation_exclusions, read back by the matching
        # _finish_* method - see async_step_streak_overrides docstring for
        # why the field key itself isn't parseable anymore.
        self._streak_field_entities: dict[str, str] = {}
        self._exclude_field_entities: dict[str, str] = {}
        # The plain (non-per-item) field submitted alongside each group's
        # entity/automation picker - held here so the *second* screen's
        # _finish_* call can still include it (see async_step_entities /
        # async_step_automations).
        self._pending_ignored_entities: list[str] = []
        self._pending_exclude_off_automations: bool = False

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["general", "entities", "automations"],
        )

    async def async_step_general(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self._finish_general(user_input)

        current_threshold = self.config_entry.options.get(
            CONF_UNAVAILABLE_THRESHOLD_MINUTES, DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES
        )
        current_notify_failed = self.config_entry.options.get(
            CONF_NOTIFY_FAILED_AUTOMATIONS, DEFAULT_NOTIFY
        )
        current_notify_linked = self.config_entry.options.get(
            CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE, DEFAULT_NOTIFY
        )
        current_excluded_labels = self.config_entry.options.get(
            CONF_EXCLUDED_LABELS, DEFAULT_EXCLUDED_LABELS
        )
        current_streak_threshold = self.config_entry.options.get(
            CONF_FAILURE_STREAK_THRESHOLD, DEFAULT_FAILURE_STREAK_THRESHOLD
        )
        current_ignored_error_texts = self.config_entry.options.get(
            CONF_IGNORED_ERROR_TEXTS, DEFAULT_IGNORED_ERROR_TEXTS
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UNAVAILABLE_THRESHOLD_MINUTES, default=current_threshold
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=1440, mode="box")
                ),
                vol.Optional(
                    CONF_EXCLUDED_LABELS, default=current_excluded_labels
                ): selector.LabelSelector(selector.LabelSelectorConfig(multiple=True)),
                vol.Required(
                    CONF_NOTIFY_FAILED_AUTOMATIONS, default=current_notify_failed
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE,
                    default=current_notify_linked,
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_FAILURE_STREAK_THRESHOLD, default=current_streak_threshold
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=20, mode="box")
                ),
                # Free-text tag list (no predefined choices, user types
                # their own) - HA's standard pattern for this shape of
                # field, same widget style as the multi-select selectors
                # elsewhere in this flow. See CONF_IGNORED_ERROR_TEXTS in
                # const.py.
                vol.Optional(
                    CONF_IGNORED_ERROR_TEXTS, default=current_ignored_error_texts
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[], multiple=True, custom_value=True, mode="list"
                    )
                ),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    def _entity_display_name(self, entity_id: str) -> str:
        """Friendly name for `entity_id`, falling back to the entity_id
        itself if it has no current state (e.g. temporarily unavailable
        at flow-build time) - same fallback pattern as
        coordinator.py's _async_get_name."""
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    async def async_step_entities(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._pending_ignored_entities = user_input.get(
                CONF_IGNORED_ENTITIES, []
            )
            streak_entities: list[str] = user_input.get(_STREAK_OVERRIDE_SELECT, [])
            if streak_entities:
                return await self.async_step_streak_overrides(
                    _entities=streak_entities
                )
            return self._finish_entities({})

        current_ignored = self.config_entry.options.get(
            CONF_IGNORED_ENTITIES, DEFAULT_IGNORED_ENTITIES
        )
        current_streak_overrides = self.config_entry.options.get(
            CONF_ENTITY_STREAK_OVERRIDES, DEFAULT_ENTITY_STREAK_OVERRIDES
        )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_IGNORED_ENTITIES, default=current_ignored
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                # Selection-only, defaults to the entities that already
                # have an override (not empty!) so opening this screen
                # and going straight to "streak_overrides" without
                # touching the picker still shows (and lets you
                # edit/keep) the existing values - see
                # async_step_streak_overrides / _finish_entities.
                vol.Optional(
                    _STREAK_OVERRIDE_SELECT,
                    default=list(current_streak_overrides),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="entities", data_schema=schema)

    async def async_step_streak_overrides(
        self,
        user_input: dict | None = None,
        _entities: list[str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Dynamically built: one number field per entity picked in
        "entities".

        Field *keys* are "<friendly name> (<entity_id>)" rather than a
        technical prefix+entity_id string, purely so the frontend's
        fallback label (raw schema key, shown whenever no strings.json
        translation matches - which a dynamic per-entity field never can)
        reads like something a human picked, not "streak__light.xyz".
        The entity_id suffix keeps keys unique even if two entities share
        a friendly name. Since the key is no longer parseable by prefix,
        `_streak_field_entities` (built here) maps each generated key
        back to its real entity_id for _finish_entities.

        `_entities` is only passed by async_step_entities on the way
        *in* (HA re-invokes a step function with only `user_input` on
        every subsequent call, including this step's own submit) -
        re-derived from `self._streak_field_entities`'s values instead
        when None, which is also why that dict has to survive between
        the two calls rather than being reset unconditionally."""
        if user_input is not None:
            return self._finish_entities(user_input)

        entities = _entities if _entities is not None else list(
            self._streak_field_entities.values()
        )
        current_streak_overrides = self.config_entry.options.get(
            CONF_ENTITY_STREAK_OVERRIDES, DEFAULT_ENTITY_STREAK_OVERRIDES
        )
        default_streak = self.config_entry.options.get(
            CONF_FAILURE_STREAK_THRESHOLD, DEFAULT_FAILURE_STREAK_THRESHOLD
        )

        self._streak_field_entities = {}
        schema_dict: dict[Any, Any] = {}
        for entity_id in entities:
            field_key = f"{self._entity_display_name(entity_id)} ({entity_id})"
            self._streak_field_entities[field_key] = entity_id
            schema_dict[
                vol.Required(
                    field_key,
                    default=current_streak_overrides.get(entity_id, default_streak),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=20, mode="box")
            )

        return self.async_show_form(
            step_id="streak_overrides", data_schema=vol.Schema(schema_dict)
        )

    async def async_step_automations(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._pending_exclude_off_automations = user_input.get(
                CONF_EXCLUDE_OFF_AUTOMATIONS, DEFAULT_EXCLUDE_OFF_AUTOMATIONS
            )
            excluded: list[str] = user_input.get(_EXCLUDED_AUTOMATIONS_SELECT, [])
            if excluded:
                return await self.async_step_automation_exclusions(
                    _entities=excluded
                )
            return self._finish_automations({})

        current_exclude_off = self.config_entry.options.get(
            CONF_EXCLUDE_OFF_AUTOMATIONS, DEFAULT_EXCLUDE_OFF_AUTOMATIONS
        )
        current_excluded_automations = self.config_entry.options.get(
            CONF_EXCLUDED_AUTOMATIONS, DEFAULT_EXCLUDED_AUTOMATIONS
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_EXCLUDE_OFF_AUTOMATIONS, default=current_exclude_off
                ): selector.BooleanSelector(),
                # Automation domain only, see const.py docstring for why.
                # Defaults to the automations that already have an
                # exclusion configured - same "don't wipe on re-save"
                # reasoning as the streak picker above.
                vol.Optional(
                    _EXCLUDED_AUTOMATIONS_SELECT,
                    default=list(current_excluded_automations),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        multiple=True, domain="automation"
                    )
                ),
            }
        )
        return self.async_show_form(step_id="automations", data_schema=schema)

    async def async_step_automation_exclusions(
        self,
        user_input: dict | None = None,
        _entities: list[str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Dynamically built: one multi-select per automation picked in
        "automations". Same field-key/mapping approach as
        async_step_streak_overrides - see its docstring."""
        if user_input is not None:
            return self._finish_automations(user_input)

        entities = _entities if _entities is not None else list(
            self._exclude_field_entities.values()
        )
        current_excluded_automations = self.config_entry.options.get(
            CONF_EXCLUDED_AUTOMATIONS, DEFAULT_EXCLUDED_AUTOMATIONS
        )

        self._exclude_field_entities = {}
        schema_dict: dict[Any, Any] = {}
        for entity_id in entities:
            field_key = f"{self._entity_display_name(entity_id)} ({entity_id})"
            self._exclude_field_entities[field_key] = entity_id
            schema_dict[
                vol.Optional(
                    field_key,
                    # New entry defaults to "excluded from both", matching
                    # CONF_EXCLUDED_LABELS' existing both-sensors behaviour
                    # until the user narrows it down.
                    default=current_excluded_automations.get(
                        entity_id, EXCLUSION_SCOPES
                    ),
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=EXCLUSION_SCOPES, multiple=True, mode="list"
                )
            )

        return self.async_show_form(
            step_id="automation_exclusions", data_schema=vol.Schema(schema_dict)
        )

    def _finish_general(
        self, user_input: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        # Baseline is the *current* saved options, not a fresh dict - this
        # branch never touches CONF_IGNORED_ENTITIES/
        # CONF_ENTITY_STREAK_OVERRIDES/CONF_EXCLUDE_OFF_AUTOMATIONS/
        # CONF_EXCLUDED_AUTOMATIONS, so they must be carried over
        # untouched rather than silently reset (see class docstring).
        data = dict(self.config_entry.options)
        data.update(user_input)
        return self.async_create_entry(title="", data=data)

    def _finish_entities(
        self, overrides_input: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        data = dict(self.config_entry.options)
        data[CONF_IGNORED_ENTITIES] = self._pending_ignored_entities
        data[CONF_ENTITY_STREAK_OVERRIDES] = {
            self._streak_field_entities[key]: value
            for key, value in overrides_input.items()
            if key in self._streak_field_entities
        }
        return self.async_create_entry(title="", data=data)

    def _finish_automations(
        self, overrides_input: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        data = dict(self.config_entry.options)
        data[CONF_EXCLUDE_OFF_AUTOMATIONS] = self._pending_exclude_off_automations
        data[CONF_EXCLUDED_AUTOMATIONS] = {
            self._exclude_field_entities[key]: value
            for key, value in overrides_input.items()
            if key in self._exclude_field_entities
        }
        return self.async_create_entry(title="", data=data)
