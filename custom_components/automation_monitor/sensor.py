"""Sensor platform for Automation Monitor: a single collection sensor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AutomationMonitorCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AutomationMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FailedAutomationsSensor(coordinator, entry)])


class FailedAutomationsSensor(CoordinatorEntity[AutomationMonitorCoordinator], SensorEntity):
    """Number of currently failed automations, with details as attributes."""

    _attr_has_entity_name = True
    _attr_name = "Failed automations"
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
