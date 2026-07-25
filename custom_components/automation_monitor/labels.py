"""Label-based exclusion check, shared by both coordinators.

HA-touching (needs entity_registry/device_registry) - unlike
classification.py/linked_entities.py/notifications.py, not unit-tested
directly here, same category as coordinator.py/
linked_entities_coordinator.py (verify live instead).

Labels are HA's own cross-cutting tagging feature (Settings -> Areas,
labels & zones -> Labels), assignable to entities and devices
independently of domain/integration. Picked via a LabelSelector in the
options flow (see config_flow.py, CONF_EXCLUDED_LABELS in const.py) - a
user labels whatever they want excluded instead of hand-picking
entity_ids.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er


def entity_has_excluded_label(
    hass: HomeAssistant, entity_id: str, excluded_labels: set[str]
) -> bool:
    """True if `entity_id` itself, or the device it belongs to, carries
    any of `excluded_labels`. Both are checked - a label put on a device
    (e.g. "seasonal") should exclude all of that device's entities, not
    just ones labeled individually. `entity_id` may be an automation
    (checked by coordinator.py) or any referenced entity (checked by
    linked_entities_coordinator.py) - same check either way."""
    if not excluded_labels:
        return False

    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get(entity_id)
    if entry is None:
        return False

    if entry.labels & excluded_labels:
        return True

    if entry.device_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(entry.device_id)
        if device is not None and device.labels & excluded_labels:
            return True

    return False
