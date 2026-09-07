# Changelog

All notable changes to Automation Monitor are documented here.

## [0.10.1] - 2026-09-07

- Fixed: a consolidated automation with several independent triggers
  (e.g. one "lighting automation" reacting separately to presence
  detectors, a remote control, and the sun's position via a `choose:`)
  could lose a tracked failure without it ever being fixed. `.data`/the
  streak counter were keyed purely by automation entity_id - a successful
  run on one trigger's branch wrongly cleared a still-broken *other*
  trigger's branch, since both only ever wrote to the one slot shared by
  the whole automation, even though Home Assistant's own trace history
  kept showing the original error. Reported by **@schabau** (issue #5),
  with a real multi-trigger automation and a screenshot of the mismatch
  between HA's trace view and `sensor.failed_automations`.

  New `trigger_fingerprint.py` identifies which of an automation's
  configured triggers actually caused a given run (`trigger.id` from the
  trace's trigger step, which HA itself already defaults to the
  trigger's list position when the user hasn't set an explicit `id:`),
  falling back to a constant sentinel for a manually-triggered run (the
  `automation.trigger` service, "Run actions" in the UI, ...). The
  coordinator now keys `.data`/the streak counter by (entity_id,
  fingerprint) together instead of entity_id alone, so independent
  triggers on the same automation are tracked - and can independently
  fail, recover, and build up their own consecutive-failure streak -
  without clobbering each other. `automation_monitor.reset
  entity_id: automation.xyz` still clears *all* of that automation's
  entries at once (there's no way to target one specific trigger), not
  just one - see README "Actions".

  One practical effect: `sensor.failed_automations`'s `automations`
  attribute can now list the *same* automation more than once at the
  same time, one entry per currently-failing trigger - a Lovelace card
  or notification automation iterating that attribute already handles
  this correctly with no changes needed, since it was always a list.

  Verified against a live HA 2026.7.4 instance (2026-09-07): a real
  two-trigger test automation confirmed the trace's trigger-step shape
  (`trigger/<idx>`, `changed_variables.trigger.id`) this relies on, for
  both a normal trigger firing and a manually-triggered run - not
  documented public API, see trigger_fingerprint.py module docstring.
  `python -m py_compile` and the full pytest suite (including new
  tests/test_trigger_fingerprint.py) pass.

## [0.10.0] - 2026-08-26

- Added: **ignored error texts** - a new General settings option, a
  free-text list of substrings checked against a failure's error message.
  If any one matches, that run never counts as a failure at all (no
  streak change, not flagged, no Logbook event), even though it's a
  genuine error - narrower than excluding the whole automation/entity,
  which drops it regardless of *why* it failed. Other, different failures
  on the same automation are still caught and flagged normally. Requested
  by a real user ("Micha", forum feedback) who wanted one specific,
  known-flaky error (a transient device connection error) silenced
  without losing coverage of everything else that automation might fail
  on. Plain substring matching, not regex, to match how it was requested.
  See README "Failure classification" and
  [TECHNICAL.md](TECHNICAL.md#ignored-error-texts).

  Live-verified on the local Docker test instance: two nearly-identical
  test automations (`stop: <text> / error: true`), one with a text
  matching a configured filter, one without. The matching one triggered
  genuinely but never appeared in `sensor.failed_automations` and
  produced no Logbook entry; the non-matching one was flagged normally
  with the exact configured error text and did produce a Logbook "failed"
  entry - confirms the filter suppresses the specific case without
  affecting unrelated failures.

## [0.9.1] - 2026-08-06

- Fixed: on a non-English Home Assistant instance, both sensors' entity_id
  was generated from the *translated* name on first setup (e.g.
  `sensor.fehlgeschlagene_automationen` on a German instance instead of
  `sensor.failed_automations`), silently breaking every entity_id in the
  README's example cards/automations. Both sensors now pin
  `suggested_object_id` to a fixed English slug, independent of UI
  language - the displayed name is still fully translated as before.
  Reported by **Martin Heinze** (issue #4): German HA 2026.7.4, v0.9.0.
  Only affects entities created from now on - existing installs keep
  their already-created (localized) entity_id; rename manually via
  Settings → Entities → pencil icon, or remove and re-add the integration
  for a fresh one.

## [0.9.0] - 2026-08-02

- Removed `update.automation_monitor` (and its GitHub-polling
  `update_coordinator.py`) entirely. Reported by **Klaus** via forum
  feedback: the entity showed an update as available but wouldn't let him
  install it, which read as broken. Investigated by reading HACS's own
  source (`custom_components/hacs/update.py`): HACS creates its own
  `UpdateEntity` for *every* repository in `hacs.repositories.list_downloaded`
  - defined generically as "any repo with `data.installed = True`", with
  no distinction between the default store and a custom repository - and
  that entity has full `UpdateEntityFeature.INSTALL` support, i.e. it can
  actually perform the update. This directly contradicts what this
  project previously assumed and documented (`const.py`: "HACS never
  creates its own update.* entity for it... confirmed absent on a live
  instance") - live-verified on the local Docker test instance by
  actually installing this integration through HACS as a custom
  repository: both `update.automation_monitor` (ours, no install
  capability) and `update.automation_monitor_update` (HACS's own, fully
  functional) existed side by side. For the HACS-based install path this
  project's Installation section actually recommends, our own entity was
  pure redundant noise at best and, per Klaus's report, actively
  misleading at worst - two "update available" cards for the same thing,
  only one of which does anything. Considered keeping it only for manual
  (non-HACS) installs (detecting at runtime whether HACS already manages
  this integration and skipping entity creation if so), but rejected:
  no stable/official HACS API for that check, and a permanently
  split-behavior entity depending on install method wasn't worth the
  added complexity for what's likely a small minority of installs. A
  manual install now has no automatic update detection at all - see
  README "Updating" for what to do instead in each case.
- Added Logbook history: `sensor.failed_automations` and
  `sensor.linked_entities_unavailable` are otherwise fully stateless (no
  persistence across restarts, by design - see README "Usage"), so there
  was previously no way to see *when* a problem started or was resolved
  without catching it live. Four new events
  (`automation_monitor_failure_detected`/`_resolved`,
  `automation_monitor_linked_entity_unavailable`/`_available`) now fire
  once per genuine flag/resolve *transition* (not on every repeated
  coordinator update, e.g. the linked-entities 20-minute safety-net
  rebuild), described via a new `logbook.py` module following the exact
  pattern HA core's own `automation` integration uses
  (`homeassistant/components/automation/logbook.py`) - no manifest
  dependency declaration needed, confirmed against that same core source
  that `automation`'s manifest doesn't list one either. Shows up under
  **Settings → Activity** (labeled "Logbook" in older HA versions - the
  sidebar entry was renamed to "Activity"/"Aktivität" in a more recent
  frontend release). Independent of the Repairs-issue toggles (General
  settings): this always fires, on by default, same as HA's own
  `automation_triggered` event - a user may want Logbook/Activity history
  without wanting Repairs pop-ups, or vice versa. Live-verified on a new
  local Docker-based test instance (no `.208`/SSH involved - see
  Contributing): triggering and resolving a test failure produced
  "<name> failed: <error>" / "<name> recovered" entries, and flapping a
  linked test entity produced "<name> became unavailable (referenced by
  an automation/script/scene)" / "<name> became available again", all
  visible via the real `/api/logbook/` endpoint.

## [0.8.1] - 2026-07-29

- Fixed a `sensor.failed_automations` classification blind spot: a step
  using `continue_on_error: true` could swallow a genuine runtime error
  and let the run complete as `script_execution: "finished"` -
  indistinguishable from an error-free success, so it was never flagged.
  Raised by **Micha** via forum feedback, worried about exactly this.
  Verified against the real HA source (`homeassistant/helpers/script.py`,
  `_handle_exception`): `continue_on_error` only ever suppresses a
  genuine `HomeAssistantError` from an integration's own service call;
  config/typo errors (`ServiceNotFound`, bad templates, invalid entity
  format, ...) are explicitly excluded and always abort regardless, so
  those were never affected. `coordinator.py` now scans every step (not
  just `last_step`, since a suppressed error isn't necessarily the last
  one that ran) for a set `error` field whenever a run reports
  "finished" (new `_find_suppressed_error_step`); `classification.
  is_execution_failure` gained a `finished_run_had_suppressed_error`
  parameter, same shape as the existing `aborted_step_had_error`. Unit
  tests added. Live-verified on .208 with a safe test automation (calls
  `homeassistant.reload_config_entry` with a bogus `entry_id`, raising a
  real error without touching any actual device): the run completed as
  "finished" but was still correctly flagged, with the right step and
  error message.
- Documented what the Repairs "Ignorieren"/"Ignore" button actually does
  (asked by **Micha**): verified against the real HA source
  (`homeassistant/helpers/issue_registry.py`,
  `homeassistant/components/repairs/websocket_api.py`) it sets a
  `dismissed_version` marker that hides the issue from the main Repairs
  list without deleting it, and - importantly - this integration's own
  update-in-place behavior (fresh error message/timestamp on a repeated
  failure) explicitly preserves that marker, so an ignored issue stays
  ignored through repeated occurrences of the same problem. It only
  reappears once the issue is actually deleted and later re-created from
  scratch, i.e. the automation/entity has to genuinely recover at least
  once before failing again.
- Added scenes as a third tracked source for
  `sensor.linked_entities_unavailable`, alongside automations and
  scripts - an entity referenced in a scene's `entities:` mapping that's
  currently `unavailable` was previously invisible to this integration
  even though the same silent-skip failure mode applies to scenes too.
  Scenes turned out simpler to support than automations/scripts: no
  action sequence, no device/area targets to resolve - HA's own
  `entities_in_scene` helper (`homeassistant/components/homeassistant/
  scene.py`) already returns the flat entity list directly, so no
  `_domain_scoped_targets`-style logic was needed. `exclude_off_automations`
  and `excluded_automations` remain automation-only (scenes have no
  on/off state at all - activating one doesn't leave it "on" - and
  weren't part of what was asked for); `excluded_labels` already worked
  for any domain generically and needed no change. `referenced_by`
  links for a scene source use the same `/config/scene/edit/<id>`
  pattern as automation/script (not independently verified live, unlike
  that pattern for automation/script). Live-verified on .208: a test
  scene referencing a test helper entity, that entity set unavailable,
  correctly flagged with `referenced_by: scene.<id>` and a matching
  Repairs issue.

## [0.8.0] - 2026-07-27

- Added a failure streak threshold for `sensor.failed_automations`: an
  automation now needs a configurable number of *consecutive* failures
  (default 1, i.e. unchanged from before) before it's flagged, instead of
  always flagging on the very first one. Requested by **AKie** (forum
  feedback) whose Zigbee mesh occasionally times out on the first attempt
  but succeeds on retry - a one-off blip isn't worth flagging, but a
  genuinely repeated failure still is. Tracked per-automation in-memory
  (`coordinator.py`, not persisted across restarts, same as the rest of
  this integration's state); the `reset` action now also resets the
  streak count, not just the tracked failure, so a reset automation
  doesn't immediately re-flag itself on its next failure.
- Added a per-entity override for the streak threshold above (Options →
  Entities → "Entities with an individual streak threshold") - lets one
  specific flaky device get more tolerance than the global default,
  rather than raising the threshold for every automation. Matched via
  direct `entity_id` references only (an automation's triggers/
  conditions/actions), not via device/area targets - a deliberate scope
  cut. If an automation touches several overridden entities, the highest
  threshold among them wins.
- Added per-automation, per-sensor exclusion (Options → Automations →
  "Automations with individual per-sensor exclusion") - narrower than
  the existing excluded-labels field (which always excludes an automation
  from *both* sensors at once): lets one automation be excluded from just
  `sensor.failed_automations` while its referenced entities are still
  tracked by `sensor.linked_entities_unavailable` (other automations may
  reference the same entities), or vice versa.
- Restructured the Options flow from a single form into a three-way menu
  (General settings / Entities / Automations), grouping settings by *what
  they configure* rather than by which feature introduced them -
  `ignored_entities` and `exclude_off_automations` moved out of "General"
  into the Entities/Automations groups they actually belong to. Went
  through several iterations based on live feedback before landing here;
  the per-entity/per-automation override fields each need a second
  screen (entity/automation picker, then one input field per picked
  item) since HA's selectors have no single widget for "entity + value"
  pairs - field labels show "‹friendly name› (‹entity_id›)" rather than
  a raw entity_id, and the picker screen always defaults to whatever's
  already configured so re-opening it without touching the picker can't
  silently wipe existing overrides.
- **Migrated from persistent notifications to Repairs issues**
  (Settings → System → Repairs) for both sensors' optional
  "notify" toggles. `persistent_notification.async_create()` (HA's
  bell-icon notification) has no per-user/admin targeting at all -
  verified against the real HA core source: it broadcasts globally to
  every connected client via a shared dispatcher. A real user reported
  non-admin household members seeing these, which isn't appropriate for
  what's fundamentally an admin/maintenance concern - Repairs is
  admin-only by design. One issue per currently-failed automation /
  currently-unavailable linked entity now (not one combined card),
  created/updated/deleted in lockstep with the sensor data
  (`issue_registry.async_create_issue`/`async_delete_issue` in
  `__init__.py`'s `_sync_issues`, replacing the old
  `_async_sync_notification`). `notifications.py`'s hand-rolled
  per-language string table (needed because persistent-notification text
  had no way to hook into HA's translation system) is gone entirely -
  Repairs issues use HA's standard `strings.json`/`translations/<lang>.json`
  mechanism via `translation_key`/`translation_placeholders`, same as
  everything else in this integration. `notifications.py` replaced by
  `issues.py` (pure placeholder-building, same testing approach).
  Live-verified on .208: issue creation, update-in-place on a repeated
  failure, deletion on resolution, and deletion via the `reset` action,
  for both sensors.

## [0.7.3] - 2026-07-27

- Added a new `update.automation_monitor` entity that checks this repo's
  GitHub Releases for a version newer than what's installed, and links
  straight to the release notes. Detection only - no install/backup
  support (`UpdateEntityFeature(0)`), same "detect and expose, don't act"
  scope as the two sensors; installing an update is still done the normal
  way (HACS, or a manual copy + restart). Added because this integration
  isn't on the default HACS store yet (see README Installation), so HACS
  never creates its own per-repository update entity for it - confirmed
  absent on a live instance (only `update.hacs_update` existed, nothing
  for either custom-repository integration installed there). Polls once
  every 12h (`update_coordinator.py`), plus once immediately on
  setup/restart so a fresh install doesn't have to wait hours for a
  first result; a failed check (GitHub unreachable/rate-limited) leaves
  the entity `unavailable` rather than guessing.
  Two bugs caught via live testing on .208 before release:
  - `integration.version` is an `AwesomeVersion` (a `str` subclass with
    its own `__eq__`), not a plain `str` - assigning it directly to
    `_attr_installed_version` crashed entity setup with "Not a valid
    AwesomeVersion object" the moment HA's entity-attribute-caching
    compared it against its internal sentinel. Fixed by casting to
    `str()` explicitly before storing.
  - The entity initially used `has_entity_name = True` with a generic
    `translation_key`/name ("Update") and no device to group it under -
    resolved to the unhelpful, collision-prone entity_id `update.update`
    instead of something identifiable. Fixed by naming it "Automation
    Monitor" instead, giving `update.automation_monitor`. Note for any
    future rename like this: an already-registered entity_id doesn't
    change just because the translation does - the stale registry entry
    has to be removed (with HA fully stopped, not just restarted, or its
    own shutdown-time registry save silently undoes a live-edited
    registry file) before the new name takes effect.

## [0.7.2] - 2026-07-26

- Fixed a stale persistent notification surviving a config-entry reload
  (e.g. saving any Options field) with data that no longer matched
  reality: `sensor.failed_automations`/`sensor.linked_entities_unavailable`
  correctly reset to empty on reload (both coordinators are recreated from
  scratch), but the notification listeners in `__init__.py` only run on a
  *subsequent* coordinator update (`coordinator.async_add_listener`)
  - never on setup itself, since each coordinator's `self.data` is set
  directly in `__init__` rather than via `async_set_updated_data()`. A
  notification already shown before the reload (e.g. a real tracked
  failure) was therefore left displaying stale, now-incorrect data
  until the next actual trigger/state-change event happened to come in
  - which, for a fixed problem or a quiet system, could be a long time
  or never. `async_setup_entry` now calls both notification-sync
  callbacks once explicitly right after registering them as listeners,
  so setup (including every options-triggered reload) always reconciles
  the notification to current reality immediately. Found via live
  testing on .208: toggled `notify_failed_automations` off while a real
  tracked failure and its notification were both active - the sensor
  reset to `0` as expected, but the notification kept showing the old
  failure until this fix. Live-verified after the fix (full restart,
  since this is a `.py` change): the stale notification is now dismissed
  immediately on setup.

## [0.7.1] - 2026-07-25

- Fixed the linked-entities-unavailable sensor over-attributing "used by"
  for area/device-targeted automations and scripts (reported by
  **Supermario** in #1: a media_player falsely shown as "used by" several
  light/climate/cover automations that merely shared its area, none of
  which ever call a media_player service). The reference-map builder
  previously expanded
  an automation/script's area or device target to *every* entity in that
  area/device regardless of domain - `light.turn_off` with
  `area_id: eg` was treated as referencing a `media_player.*` entity
  simply for being physically in the same area, even though that action
  can never affect it. `_referenced_entities_for()` in
  `linked_entities_coordinator.py` now walks the actual action sequence
  itself (`_domain_scoped_targets()`, new) and pairs each area_id/
  device_id target with the domain of the service/device-automation call
  it came from, only counting entities of that same domain as
  referenced. Direct entity_id references (from triggers, conditions, or
  actions) are unaffected - always a deliberate reference regardless of
  domain. Also corrected a docstring claim that the old (over-broad)
  approach matched HA's own device "Related" tab - checked against HA's
  `search` component source: the Related tab only ever looks for direct
  device/entity references, never expands "automation targets this
  area, entity X is also in that area" the way the old code here did.
  Live-verified on a real instance: a domain-matched entity in a
  targeted area is still correctly flagged as "used by" the right
  automation/script, while a domain-mismatched entity on the same device
  in the same area is correctly no longer included, even though it was
  eligible under the old code (enabled, in the targeted area).

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
