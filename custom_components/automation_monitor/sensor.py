"""Sensor platform for Automation Monitor: two collection sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AutomationMonitorRuntimeData
from .const import DOMAIN
from .coordinator import AutomationMonitorCoordinator
from .linked_entities_coordinator import LinkedEntitiesCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime_data: AutomationMonitorRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FailedAutomationsSensor(runtime_data.failures, entry),
            LinkedEntitiesUnavailableSensor(runtime_data.linked_entities, entry),
        ]
    )


class FailedAutomationsSensor(CoordinatorEntity[AutomationMonitorCoordinator], SensorEntity):
    """Number of currently failed automations, with details as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "failed_automations"
    # Without this, HA derives the initial entity_id from the *translated*
    # name (has_entity_name + translation_key resolves through the
    # user's UI language) - on a non-English instance that means
    # e.g. `sensor.fehlgeschlagene_automationen` on first setup, silently
    # breaking every entity_id in the README's example cards/automations.
    # suggested_object_id pins the slug source to this fixed, English
    # string instead, independent of `_attr_translation_key`/UI language -
    # the *displayed* name is still fully translated as before. Reported
    # by a real user (issue #4, 2026-08-06, German-language HA 2026.7.4).
    _attr_suggested_object_id = "failed_automations"
    _attr_icon = "mdi:robot-confused"

    def __init__(self, coordinator: AutomationMonitorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_failed"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, list[dict]]:
        return {"automations": list(self.coordinator.data.values())}


class LinkedEntitiesUnavailableSensor(
    CoordinatorEntity[LinkedEntitiesCoordinator], SensorEntity
):
    """Number of entities referenced by automations/scripts that are
    currently unavailable, with details as attributes. Complements
    FailedAutomationsSensor: catches devices that are simply unreachable,
    which HA's trace data never records as a failure at all (see README
    "Known limitations")."""

    _attr_has_entity_name = True
    _attr_translation_key = "linked_entities_unavailable"
    # See FailedAutomationsSensor above - same fix, same reason.
    _attr_suggested_object_id = "linked_entities_unavailable"
    _attr_icon = "mdi:lan-disconnect"

    def __init__(self, coordinator: LinkedEntitiesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_linked_unavailable"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, list[dict]]:
        return {"entities": list(self.coordinator.data.values())}
