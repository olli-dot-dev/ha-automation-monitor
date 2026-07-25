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

# Options flow: skip automations that are currently turned off (state
# "off" - their own on/off toggle, e.g. Settings -> Automations, or
# automation.turn_off) when building the linked-entities reference map.
# Off by default (preserves existing behaviour): a turned-off automation's
# referenced entities are still tracked/flagged unless a user opts into
# this. Requested by a real user with automations intentionally disabled
# seasonally (winter-only battery/solar charge-limit automations) whose
# referenced entities were getting flagged despite posing no actual risk
# while the automation can't run at all.
#
# Deliberately does NOT apply to scripts: a script entity's "off" state
# means "not currently running" (idle), not "disabled" - scripts have no
# enable/disable concept at all, unlike automations. Filtering scripts by
# state would incorrectly exclude nearly every script nearly all the time.
CONF_EXCLUDE_OFF_AUTOMATIONS = "exclude_off_automations"
DEFAULT_EXCLUDE_OFF_AUTOMATIONS = False

# Options flow: HA's own labels (Settings -> Areas, labels & zones ->
# Labels) whose entities/devices should be excluded from monitoring
# entirely - picked via a LabelSelector rather than typed by hand, so a
# user just labels whatever they want excluded instead of maintaining an
# entity_id list here too. Two effects, mirroring "Automationen UND
# Entitaeten, Geraete ausschliessen" (as requested):
# - An automation carrying one of these labels is skipped entirely by the
#   failed-automations sensor (never flagged even if it errors), and
#   skipped as a linked-entities reference-map source (same treatment as
#   CONF_EXCLUDE_OFF_AUTOMATIONS above).
# - An entity or device carrying one of these labels is excluded from the
#   linked-entities-unavailable check entirely, same as
#   CONF_IGNORED_ENTITIES but driven by a label instead of a hand-picked
#   entity_id - a label on a device excludes all of that device's
#   entities, not just ones labeled individually. See labels.py.
CONF_EXCLUDED_LABELS = "excluded_labels"
DEFAULT_EXCLUDED_LABELS: list[str] = []

# How often to rebuild the automation/script -> referenced-entity map as a
# safety net, since there is no HA event for "a script's content changed"
# (confirmed absent from the installed HA source - automation has
# EVENT_AUTOMATION_RELOADED, script has no equivalent). Cheap: in-memory
# only, bounded by automation+script count. See linked_entities_coordinator.py.
LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES = 20
