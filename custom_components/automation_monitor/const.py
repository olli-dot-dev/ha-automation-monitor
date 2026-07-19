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

# Options flow: entities to exclude from the linked-entities-unavailable
# check entirely (e.g. a device that's expected to be offline for long
# stretches on purpose) - never tracked, never flagged, regardless of how
# long they stay unavailable. See config_flow.py / linked_entities.py.
CONF_IGNORED_ENTITIES = "ignored_entities"
DEFAULT_IGNORED_ENTITIES: list[str] = []

# Options flow: opt-in persistent notifications (HA's built-in in-UI
# notification, not a push/mobile notification), one toggle per sensor so
# either can be enabled independently - see notifications.py / __init__.py.
# Off by default: keeps the MVP's "detection only, no notifications"
# behaviour unless a user explicitly asks for it.
CONF_NOTIFY_FAILED_AUTOMATIONS = "notify_failed_automations"
CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE = "notify_linked_entities_unavailable"
DEFAULT_NOTIFY = False

# Fixed persistent_notification IDs (one per sensor) so re-creating one
# updates/replaces the existing card in place instead of piling up
# duplicates, and so it can be looked up again to dismiss it (toggle turned
# off, or the integration unloaded).
NOTIFICATION_ID_FAILED_AUTOMATIONS = f"{DOMAIN}_failed_automations"
NOTIFICATION_ID_LINKED_ENTITIES_UNAVAILABLE = f"{DOMAIN}_linked_entities_unavailable"

# How often to rebuild the automation/script -> referenced-entity map as a
# safety net, since there is no HA event for "a script's content changed"
# (confirmed absent from the installed HA source - automation has
# EVENT_AUTOMATION_RELOADED, script has no equivalent). Cheap: in-memory
# only, bounded by automation+script count. See linked_entities_coordinator.py.
LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES = 20
