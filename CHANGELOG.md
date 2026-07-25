# Changelog

All notable changes to Automation Monitor are documented here.

## [0.7.0] - 2026-07-25

- Added a "Skip automations that are turned off" toggle to the Options
  flow (off by default). Requested by a real user with automations
  intentionally turned off seasonally (winter-only solar/battery
  charge-limit automations), whose referenced entities were still being
  tracked and flagged by `sensor.linked_entities_unavailable` despite the
  automation being unable to run at all - the reference-map build walks
  each automation's *config*, which is unaffected by its current on/off
  state. Only ever applies to automations, never scripts (a script's
  "off" state means idle, not disabled - it has no enable/disable concept
  to filter by). Toggling an automation on/off is picked up immediately
  via a dedicated state-change subscription (only active while this
  option is on), not just on the next periodic rebuild - none of the
  existing rebuild triggers (`automation_reloaded`, entity registry
  updates) fire for a plain on/off toggle. Not yet verified live against
  a running HA instance.
- Added German (`de`) translation, requested by a user who found the
  (English-only) persistent notifications hard to follow. Automatically
  follows HA's own system language (`hass.config.language`), falling
  back to English otherwise - nothing to configure. Two separate
  mechanisms: entity names and the Options dialog now go through HA's
  standard `strings.json`/`translations/<lang>.json` system (previously
  English-only there too - `translations/de.json` added, entity names
  switched from hardcoded `_attr_name` to translatable
  `_attr_translation_key`); persistent notification text is translated
  by hand via a new small string table in `notifications.py`
  (`build_failed_automations_message`/`build_linked_entities_message`
  gained an optional `lang` parameter), since that text is built at
  runtime from live data and HA's translation system doesn't cover that
  at all. See README "Language" for how to add another language. Not
  yet verified live with `hass.config.language` actually set to `de`.
- Added French (`fr`) and Spanish (`es`) translations, same mechanism as
  German above: `translations/fr.json`/`translations/es.json` for entity
  names and the Options dialog, plus `fr`/`es` entries in
  `notifications.py`'s `_STRINGS` table for persistent notification text.
  Not yet verified live with `hass.config.language` actually set to `fr`
  or `es`.
- Added an "Excluded labels" field (multi-select `LabelSelector`) to the
  Options flow, using HA's own label feature instead of a hand-picked
  entity_id list (new `labels.py`). An automation carrying one of these
  labels is skipped entirely by both sensors: never flagged by the
  failed-automations sensor even if it errors (checked fresh on every
  trigger in `coordinator.py`), and skipped as a reference-map source in
  `linked_entities_coordinator.py` (same treatment as the existing "skip
  turned-off automations" toggle). An entity or device carrying one of
  these labels is excluded from the linked-entities-unavailable check the
  same way an ignored entity already is - a device-level label excludes
  all of that device's entities. Label changes are picked up on the next
  periodic rebuild or `rebuild_linked_entities` service call for the
  linked-entities sensor (same lag as a script content edit), and
  immediately (next trigger) for the failed-automations sensor.
  Live-verified: a labeled automation errored and was correctly never
  flagged; a labeled *device* (label applied to the device, not the
  entity) stayed genuinely unavailable but correctly dropped out of
  `sensor.linked_entities_unavailable` after a restart, confirming both
  the exclusion itself and the device-to-entity label inheritance.

## [0.6.1] - 2026-07-19

- Each entity in the `sensor.linked_entities_unavailable` notification
  now also shows its raw `entity_id` in copyable inline-code formatting,
  and the notification ends with a link to the integration's own
  settings page (`/config/integrations/integration/automation_monitor`)
  plus a hint to copy an entity_id above and paste it in - live-verified
  (settings link opens the right page). Makes adding a listed entity to
  the ignore-list faster: no more navigating there manually or typing
  the entity_id from memory, though the actual picking-and-saving step
  in the options form still has to be done by hand - HA's options flow
  has no way to pre-fill a field from a link (confirmed while scoping
  this - no config-flow-discovery-style external-data mechanism exists
  for options flows); a few bigger alternatives (a custom settings panel
  that reads the entity from the URL and pre-selects it, an
  `ignore_entity` service, mobile actionable notifications) were
  considered and intentionally not built - decided not worth the added
  complexity for this.
- Also removed the README's "Testing notes", "Development", and "Open
  questions" sections (same reasoning as the 0.6.0 README trim).
- Documented in the README (Usage): a Home Assistant restart resets both
  sensors, since neither persists across restarts by design - and for
  `sensor.linked_entities_unavailable` specifically, this effectively
  restarts an already-broken entity's unavailable-threshold countdown
  too, since most integrations give their entities a fresh
  `last_changed` timestamp on HA startup. Learned the hard way during
  this session's live testing (repeated restarts kept resetting the test
  entities' timers, which looked like a bug before turning out to be
  expected HA behaviour).

## [0.6.0] - 2026-07-19

- Added an entity ignore-list to the Options flow: entities added there
  are excluded from the linked-entities-unavailable check entirely
  (never tracked, never flagged), regardless of how long they stay
  unavailable - useful for a device that's expected to be offline for
  long stretches on purpose. Filtered at reference-map build time in
  `build_reference_map` (`linked_entities.py`), so an already-flagged
  entity added to the list is unflagged automatically on the next
  rebuild, via the same "dropped from map" cleanup path used when an
  automation stops referencing an entity - no separate code path
  needed.
- Added optional persistent (in-UI, not push) notifications, one toggle
  each for `sensor.failed_automations` and
  `sensor.linked_entities_unavailable` in the Options flow, off by
  default. Each sensor gets exactly one notification under a fixed ID
  that's updated in place as its data changes and dismissed
  automatically once the sensor goes back to empty. Message text built
  by new pure, unit-tested functions in `notifications.py`; wired to
  each coordinator via `coordinator.async_add_listener` in
  `__init__.py`. Live-verified (bell icon, not just the recorder DB) -
  see Testing notes for the couple of narrower gaps still open (e.g.
  toggling off specifically).
- Each entity/automation name in a persistent notification is now a
  clickable Markdown link instead of plain text: a failed automation
  links to its editor (`/config/automation/edit/<unique_id>`); an
  unavailable linked entity links to its **device** page
  (`/config/devices/device/<device_id>` - route pattern confirmed
  correct against a real working URL) if it has one, falling back to
  its own entity settings page (`/config/entities/entity/<entity_id>` -
  not independently verified live, see Testing notes) if it doesn't;
  and, if known, is now followed by "used by" links to every
  automation/script that references it, each linking straight to its
  own editor. All links fall back to plain unlinked text rather than a
  dead link if the unique_id/device_id they need couldn't be resolved.
  `linked_entities_coordinator.py` now resolves and stores each flagged
  entity's `device_id`, and `referenced_by_details`
  (name/unique_id/domain per referencing automation/script) alongside
  the existing plain `referenced_by` entity_id list, which is unchanged.
- The `unavailable since` timestamp in the linked-entities notification
  is now formatted `YYYY-MM-DD HH:MM` in the local timezone (via
  `.astimezone()`), instead of the raw ISO-8601 UTC string. An earlier
  version of this within the same release cycle formatted it without
  converting the timezone first, so it displayed the correct-looking
  but actually-UTC clock value (e.g. `11:10` shown when it should have
  read `13:10`) - fixed before release, but the corrected version
  hasn't been re-confirmed live yet, see Testing notes.
- Fixed (found during live testing): saving the Options form dismissed
  both persistent notifications even when neither sensor's data had
  actually changed, because notification cleanup lived in
  `async_unload_entry` - which also runs on the reload an options save
  triggers, not just on removing the integration. Moved to the
  `async_remove_entry` hook, which HA only calls on an actual delete.
- Coordinator listeners that sync the persistent notifications are now
  wrapped in a try/except with logging - previously an exception there
  could in theory propagate out through `async_set_updated_data` into
  whatever triggered the update instead of just failing the
  notification. No live-confirmed instance of this actually happening
  (an apparent "notification never showed up" turned out to be pure
  timing, not a bug - a device's unavailable-timer kept resetting
  across the repeated restarts during that testing session), but the
  defensive fix and the debug logging it added were worth keeping.
- Trimmed the README: dropped the Status, Scope, Architecture, and Data
  model sections, which had grown stale/redundant with the more
  detailed feature sections and this changelog.

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
