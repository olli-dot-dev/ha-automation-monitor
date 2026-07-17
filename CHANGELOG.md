# Changelog

All notable changes to Automation Monitor are documented here.

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
