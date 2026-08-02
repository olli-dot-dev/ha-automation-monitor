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

# Options flow: opt-in Repairs issues (Settings -> Repairs, admin-only -
# see issues.py / __init__.py), one toggle per sensor so either can be
# enabled independently. Off by default: keeps the MVP's "detection only"
# behaviour unless a user explicitly asks for it.
#
# Was a persistent_notification (the bell-icon card) through v0.7.x -
# replaced because persistent_notification.async_create() has no
# per-user/admin concept at all (verified against the real HA core
# source, homeassistant/components/persistent_notification/__init__.py:
# it broadcasts globally to every connected client via a shared
# dispatcher, no user targeting parameter exists). A real user reported
# (2026-07-27) that non-admin household members were seeing these, which
# isn't appropriate for what is fundamentally an admin/maintenance
# concern. The Repairs system is admin-only by design instead.
CONF_NOTIFY_FAILED_AUTOMATIONS = "notify_failed_automations"
CONF_NOTIFY_LINKED_ENTITIES_UNAVAILABLE = "notify_linked_entities_unavailable"
DEFAULT_NOTIFY = False

# issue_registry issue_id prefixes (see issues.py) - one issue per
# currently-failed automation / currently-unavailable linked entity
# (`f"{prefix}:{entity_id}"`), not one combined issue per sensor. Matches
# how the Repairs page already presents multiple issues as separate,
# individually-dismissible rows - a better fit than persistent
# notification's old single-card-with-many-lines approach.
ISSUE_PREFIX_FAILED_AUTOMATION = "failed_automation"
ISSUE_PREFIX_LINKED_ENTITY_UNAVAILABLE = "linked_entity_unavailable"

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

# Options flow: how many consecutive failed runs an automation needs
# before it's flagged by sensor.failed_automations - default 1 preserves
# the original "flag on the very first failure" behaviour. Requested by a
# real user (forum feedback, 2026-07-27) whose Zigbee mesh occasionally
# times out ("device did not respond") on the first attempt but succeeds
# on a retry - a single one-off blip isn't a real problem worth flagging,
# but a *repeated* failure still is. See coordinator.py.
CONF_FAILURE_STREAK_THRESHOLD = "failure_streak_threshold"
DEFAULT_FAILURE_STREAK_THRESHOLD = 1

# Options flow: per-entity override of the streak threshold above, e.g. a
# specific Zigbee device known to be flakier than the rest of the mesh
# and deserving more tolerance than the global default. {entity_id: int}.
# Matched by direct entity_id references only (HA's own
# entities_in_automation - triggers/conditions/actions), not via
# device/area targets the way linked_entities_coordinator.py's fuller
# resolution does - a deliberate scope cut, see coordinator.py
# `_effective_streak_threshold` docstring. Configured via a two-step
# options flow (pick entities in step "init", enter each one's threshold
# in step "overrides") since HA's selectors have no single widget for
# "list of entity+number pairs" - see config_flow.py.
CONF_ENTITY_STREAK_OVERRIDES = "entity_streak_overrides"
DEFAULT_ENTITY_STREAK_OVERRIDES: dict[str, int] = {}

# Options flow: per-automation, per-sensor exclusion - {entity_id:
# [scope, ...]} where scope is one of the SCOPE_* values below. Separate
# from CONF_EXCLUDED_LABELS (which always excludes from *both* sensors at
# once): requested specifically so one automation can be excluded from
# only one sensor, e.g. a known-flaky automation excluded from
# failed_automations while its referenced entities are still tracked by
# linked_entities_unavailable (other automations may reference the same
# entities). Same two-step options flow mechanism as
# CONF_ENTITY_STREAK_OVERRIDES above - see config_flow.py.
CONF_EXCLUDED_AUTOMATIONS = "excluded_automations"
DEFAULT_EXCLUDED_AUTOMATIONS: dict[str, list[str]] = {}

SCOPE_FAILED_AUTOMATIONS = "failed_automations"
SCOPE_LINKED_ENTITIES_UNAVAILABLE = "linked_entities_unavailable"
EXCLUSION_SCOPES = [SCOPE_FAILED_AUTOMATIONS, SCOPE_LINKED_ENTITIES_UNAVAILABLE]

# Logbook events (see logbook.py) - fired once per flag/resolve
# *transition*, not on every repeated coordinator update, so the Logbook
# page reads as real history rather than being spammed by e.g. the 20-
# minute linked-entities safety-net rebuild. Independent of the Repairs-
# issue toggles above (CONF_NOTIFY_*) - a user may want Logbook history
# without wanting Repairs pop-ups, or vice versa, so this always fires
# regardless of those. No config_flow toggle of its own, matching how
# HA's own `automation_triggered` event isn't optional either.
EVENT_FAILURE_DETECTED = "automation_monitor_failure_detected"
EVENT_FAILURE_RESOLVED = "automation_monitor_failure_resolved"
EVENT_LINKED_ENTITY_UNAVAILABLE = "automation_monitor_linked_entity_unavailable"
EVENT_LINKED_ENTITY_AVAILABLE = "automation_monitor_linked_entity_available"

# How often to rebuild the automation/script -> referenced-entity map as a
# safety net, since there is no HA event for "a script's content changed"
# (confirmed absent from the installed HA source - automation has
# EVENT_AUTOMATION_RELOADED, script has no equivalent). Cheap: in-memory
# only, bounded by automation+script count. See linked_entities_coordinator.py.
LINKED_ENTITIES_REBUILD_INTERVAL_MINUTES = 20
