"""Update platform for Automation Monitor: a single entity reporting
whether a newer version is available on GitHub than what's installed.

Detection only - UpdateEntityFeature(0), no INSTALL/BACKUP support. This
project never changes anything about your Home Assistant setup or itself;
installing an update is still done the normal way (HACS, or a manual
copy+restart), same as always. See update_coordinator.py for why this
entity exists despite HACS already handling updates for most integrations.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AutomationMonitorRuntimeData
from .const import DOMAIN
from .update_coordinator import UpdateCheckCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime_data: AutomationMonitorRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AutomationMonitorUpdateEntity(
                runtime_data.update_check, entry, runtime_data.installed_version
            )
        ]
    )


class AutomationMonitorUpdateEntity(CoordinatorEntity[UpdateCheckCoordinator], UpdateEntity):
    """Reports the latest GitHub release for this integration itself."""

    _attr_has_entity_name = True
    _attr_translation_key = "update"
    _attr_supported_features = UpdateEntityFeature(0)
    _attr_title = "Automation Monitor"

    def __init__(
        self, coordinator: UpdateCheckCoordinator, entry: ConfigEntry, installed_version: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_update"
        self._attr_installed_version = installed_version

    @property
    def available(self) -> bool:
        # Unlike the two sensors (which are always available, empty just
        # means "nothing to report"), "no data" here specifically means
        # the last GitHub check failed (see UpdateCheckCoordinator) - has
        # nothing meaningful to say about a newer version, so reports
        # unavailable rather than silently claiming "up to date".
        return super().available and self.coordinator.data is not None

    @property
    def latest_version(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["version"]

    @property
    def release_url(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["release_url"]

    @property
    def release_summary(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["release_summary"]
