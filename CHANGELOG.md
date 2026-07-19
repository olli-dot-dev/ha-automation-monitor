# Changelog

All notable changes to Automation Monitor are documented here.

## [Unreleased]

- Fixed (found during live testing): the `unavailable since` timestamp in
  the linked-entities notification showed the raw UTC clock value (e.g.
  `11:10`) without converting it to local time, even though it was
  displayed without a UTC marker and so read as if it already were local
  (should have read `13:10`). `_format_timestamp` now calls
  `.astimezone()` before formatting.
- Added an entity ignore-list to the Options flow: entities added there are
  excluded from the linked-entities-unavailable check entirely (never
  tracked, never flagged), regardless of how long they stay unavailable -
  useful for a device that's expected to be offline for long stretches on
  purpose. Filtered at reference-map build time in `build_reference_map`
  (`linked_entities.py`), so an already-flagged entity added to the list
  is unflagged automatically on the next rebuild, via the same "dropped
  from map" cleanup path used when an automation stops referencing an
  entity - no separate code path needed. Not yet verified live against a
  running HA instance - see Testing notes.
- Added optional persistent (in-UI, not push) notifications, one toggle
  each for `sensor.failed_automations` and
  `sensor.linked_entities_unavailable` in the Options flow, off by
  default. Each sensor gets exactly one notification under a fixed ID
  that's updated in place as its data changes and dismissed automatically
  once the sensor goes back to empty (or the toggle is turned off).
  Message text built by new pure, unit-tested functions in
  `notifications.py`; wired to each coordinator via
  `coordinator.async_add_listener` in `__init__.py`. Not yet verified
  live against a running HA instance - see Testing notes.
- Each entity/automation name in a persistent notification is now a
  clickable Markdown link instead of plain text: a failed automation
  links to its editor (`/config/automation/edit/<unique_id>`); an
  unavailable linked entity links to its **device** page
  (`/config/devices/device/<device_id>` - the route pattern is confirmed
  correct, copied from a real working URL) if it has one, falling back to
  its own entity settings page (`/config/entities/entity/<entity_id>` -
  not independently verified live, see Testing notes) if it doesn't; and,
  if known, is now followed by "used by" links to every automation/script
  that references it, each linking straight to its own editor. All links
  fall back to plain unlinked text rather than a dead link if the
  unique_id/device_id they need couldn't be resolved.
- `linked_entities_coordinator.py` now also resolves and stores each
  flagged entity's `device_id` (via the entity registry), used by the
  device-page link above.
- Coordinator listeners that sync the persistent notifications (see
  above) are now wrapped in a try/except with logging - previously an
  exception there could in theory propagate out through
  `async_set_updated_data` into whatever triggered the update instead of
  just failing the notification. No live-confirmed instance of this
  actually happening (an apparent "notification never showed up" turned
  out to be pure timing, not a bug - a device's unavailable-timer kept
  resetting across the repeated restarts during that testing session),
  but the defensive fix and the debug logging it added were worth keeping.
- The `unavailable since` timestamp in the linked-entities notification
  is now formatted `YYYY-MM-DD HH:MM` instead of the raw ISO-8601 string.
- Fixed (found during live testing): saving the Options form dismissed
  both persistent notifications even when neither sensor's data had
  actually changed, because notification cleanup lived in
  `async_unload_entry` - which also runs on the reload an options save
  triggers, not just on removing the integration. Moved to the
  `async_remove_entry` hook, which HA only calls on an actual delete.
- `linked_entities_coordinator.py` now also resolves and stores
  `referenced_by_details` (name/unique_id/domain per referencing
  automation/script) alongside the existing plain `referenced_by`
  entity_id list, which is unchanged - purely additive, needed for the
  new "used by" notification links above.

## [0.5.0] - 2026-07-17

- Added a second, independent sensor, `sensor.linked_entities_unavailable`,
  for a failure mode the trace-based sensor cannot see at all: a service
  call targeting an entity that's currently `unavailable` is silently
  skipped by Home Assistant's core service dispatch, with no trace error
  or log signal. The new sensor instead proactively watches every entity
  referenced by your automations and scripts - directly, or via a
  `device_id`/`area_id` target - and flags any that stay continuously
  `unavailable` past a configurable threshold (default 15 minutes)
- Added an Options flow to configure that threshold without reinstalling
- Added the `automation_monitor.rebuild_linked_entities` service to force
  an immediate reference-map rebuild (useful after editing a script's
  content, which has no dedicated reload event to react to automatically)
- See README "Linked entity unavailability detection" and "Known
  limitations" context in "Why not just use Watchman" for the full
  rationale and scope decisions (only `unavailable`, not `unknown`;
  device/area target resolution included)

## [0.4.0] - 2026-07-12

- Initial implementation: `sensor.failed_automations` detects failed
  automation runs from Home Assistant's trace API and exposes them as a
  structured sensor with an `automations` attribute list
- Classification logic (`classification.py`) distinguishes genuine
  runtime errors from intended stop behaviour (e.g. a mid-sequence
  `condition:` action failing on purpose vs. a deliberate
  `stop: ... error: true`) - see README "Failure classification"
- Added the `automation_monitor.reset` service to clear tracked failures
  without waiting for a restart or a successful re-run
- Validated live against a real HA 2026.7.1 instance across all four
  target scenarios (error, mid-sequence condition action,
  `stop: ... error: true`, `mode: single` re-trigger)
