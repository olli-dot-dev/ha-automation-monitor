"""Constants for Automation Monitor."""

DOMAIN = "automation_monitor"
PLATFORMS = ["sensor"]

EVENT_AUTOMATION_TRIGGERED = "automation_triggered"

SERVICE_RESET = "reset"
SERVICE_REBUILD_LINKED_ENTITIES = "rebuild_linked_entities"
ATTR_ENTITY_ID = "entity_id"

# Options flow: how long an entity referenced by an automation/script must
# stay continuously `unavailable` before it's flagged by the linked-entities
# sensor. Configurable rather than hardcoded so it can be tuned without a
# reinstall - see config_flow.py.
CONF_UNAVAILABLE_THRESHOLD_MINUTES = "unavailable_threshold_minutes"
DEFAULT_UNAVAILABLE_THRESHOLD_MINUTES = 15

# How often to rebuild the automation/script -> referenced-entity map as a
# safety net, since there is no HA event for "a script's content changed"
# (confirmed absent from the installed HA source - automation has
# EVENT_AUTOMATION_RELOADED, script has no equivalent). Cheap: in-memory
# only, bounded by automation+script count. See linked_entities_coordinator.py.
LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES = 20
