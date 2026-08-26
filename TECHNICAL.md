# Technical details

Implementation notes, internal-HA-behavior verification, and the
reasoning behind non-obvious decisions - split out of
[README.md](README.md) to keep that focused on installing and using the
integration. Read this if you're contributing, debugging something, or
just curious how it works under the hood.

## Why not just use Watchman / HA's built-in Repairs?

Home Assistant has gained its own native config validation over the last
couple of years: Settings → System → Repairs will flag things like an
automation action referencing a service that doesn't exist at all (e.g.
a typo'd service name). That's **static** validation - the same category
[Watchman](https://github.com/dummylabs/thewatchman) covers - and it can
be checked without ever running the automation.

This matters because it's easy to pick a misleading test case: calling a
genuinely nonexistent service (`light.this_service_does_not_exist`, one
of the scenarios validated during development) gets caught by both HA's
native Repairs *and* this integration. That overlap is real but narrow -
it's the one failure mode in this project's own test suite that HA
already catches on its own, without needing this integration at all.

Where Automation Monitor is the *only* thing that catches the problem -
because the config is perfectly valid and the failure only exists at
runtime:

- A template that's syntactically valid but hits `None` or a missing key
  at runtime, depending on live state
- A deliberate `stop: ... error: true` - not a config problem at all, so
  Repairs never sees it (verified live)
- A cloud-integration service call that fails due to that service's own
  backend/network issues, *provided* the integration actually raises on
  failure instead of swallowing it

Also, structurally: HA's *own* static Repairs issues are tied to the
*config* and one-off - dismiss one and it's gone until the same issue
recurs, and none of it is queryable as sensor attributes, templatable, or
put on a dashboard the way this integration's sensors are. The sensors
are always the source of truth here, restart-independent of whatever's
shown in Repairs.

This project *does* optionally publish its own findings to Repairs too
(see [Repairs issues internals](#repairs-issues-internals) below) - but
on its own terms: one issue per currently-failed automation /
currently-unavailable entity, created and automatically deleted in
lockstep with the sensor data itself, not a one-off static check. That's
a deliberate choice for admin-only visibility (Repairs, unlike a
persistent notification, only shows to admin users) rather than a
replacement for what the sensors already do.

## Failure classification

Only genuine runtime errors count as "failed". Verified against the actual
Home Assistant 2026.7.1 source (`homeassistant/helpers/script.py`,
`homeassistant/components/automation/__init__.py`) - the real
`script_execution` values differ from what you might expect from the trace
UI:

| `script_execution` | Counts as failure? | Reason |
|---|---|---|
| `error` | Yes | Action raised an unhandled exception (unknown entity, service error, template error) |
| `disallowed_recursion_detected` | Yes | Automation triggered itself past HA's recursion guard - broken logic, not intended |
| `aborted` | **Depends** | Overloaded by HA: set both for a mid-sequence `condition:` *action* not being met (intended) and for `stop: ... error: true` / other internal aborts (real problem). Both report the identical `last_step` path shape (e.g. `action/0`) - a path-string heuristic was tried first and **misclassified a failed condition action as a failure** in live testing. The reliable signal is one level deeper: HA explicitly clears the trace step's own `error` field on a condition-fail but sets it on every other abort - only visible in the *extended* trace dict, not the short one |
| `cancelled` | No | e.g. `mode: single` re-triggered while already running - concurrency, not an error |
| `failed_single` / `failed_max_runs` | No | Run rejected by the automation's `mode:` limit - same category as `cancelled` |
| `failed_conditions` | No | The automation's *top-level* `condition:` block wasn't met. In practice HA never even fires `automation_triggered` for this case, so we never see it - listed for completeness |
| `finished` | **Depends** | Completed normally (this is what a plain success run reports - HA does **not** use the literal string `"success"`) - **unless** a step used `continue_on_error: true` to swallow a genuine runtime error, see below |

Implemented in `custom_components/automation_monitor/classification.py`,
covered by `tests/test_classification.py`. This is the most
trust-critical part of the integration - false positives make users
ignore the sensor. Validated live against a HA 2026.7.1 test instance
across all four classification scenarios (error, mid-sequence condition
action, `stop: ... error: true`, `mode: single` re-trigger) - all four
classify correctly.

One more live-testing finding: a `mode: single` automation re-triggered
while already running is often rejected by HA *before*
`automation_triggered` even fires (logged as `WARNING ... Already
running`, no trace created) - same "coordinator never sees it" pattern
as the top-level `condition:` block. The `cancelled` script_execution
handling above still matters for other paths (e.g. an automation
explicitly stopped from outside while running), just not for the most
common mode:single case.

### `continue_on_error: true` doesn't hide everything

Raised by **Micha** (forum feedback) worried a step using
`continue_on_error: true` would make a real failure invisible. Verified
against the real HA source (`homeassistant/helpers/script.py`,
`_handle_exception`): `continue_on_error` only ever suppresses a genuine
`HomeAssistantError` raised by an integration's own service call (e.g.
"device did not respond", a timeout). Config/typo errors - a nonexistent
service, a bad template, an invalid entity format - are explicitly
excluded from suppression and always abort the run regardless, so those
are caught the normal way (`script_execution == "error"`) with
`continue_on_error` having no effect at all. When `continue_on_error`
*does* suppress a genuine error, the affected step's own trace entry
still gets marked with `error` - execution just carries on instead of
aborting, so the overall run still reports `script_execution: "finished"`.
`coordinator.py` scans every step for this (not just the last one, since
a suppressed error isn't necessarily the last step that ran) whenever a
run reports "finished", and flags it the same as any other failure if
one is found. Live-verified on .208 with a safe test automation (calls
`homeassistant.reload_config_entry` with a bogus `entry_id`, so it
raises a real error without touching any actual device): the run
completed as "finished" but was still correctly flagged, with the right
step and error message.

## Data source

Trace API instead of log parsing. Watchman-style solutions parse
`system_log_event` messages with regex, which is fragile (free text,
language-dependent, changes between HA versions). Instead:

1. Listen for the `automation_triggered` event (gives the `entity_id`)
2. Poll the matching trace every 1s (up to 60s) until it reports `state: "stopped"`
3. Read the structured `script_execution` / `last_step` / per-step `error` fields from the trace

Implemented in `coordinator.py` (`_get_last_trace`), wrapped defensively
(try/except + log warning instead of crashing) since none of this is a
documented, stable public API and can change between HA versions. Two
internal details worth knowing if this breaks on a future HA version:

- Traces live in `hass.data[DATA_TRACE]` (from
  `homeassistant.components.trace.const`), keyed by
  `f"automation.{unique_id}"` - **not** the entity_id. `unique_id` is the
  automation's stable config `id:`, resolved from `entity_id` via the
  entity registry. Renaming an automation's entity_id in the UI doesn't
  change this.
- Each bucket's `.runs` is an insertion-ordered, size-limited dict; the
  last item is the current run.

Fallback if trace access turns out too unstable: reduced scope via
`system_log_event`, filtered on `logger: homeassistant.components.automation`
and `level: ERROR`. Documented as a fallback, not the primary approach.

## Linked entity unavailability detection mechanism

A second, independent sensor for a failure mode the trace-based sensor
above cannot see at all: a service call targeting an entity that's
currently `unavailable` (e.g. an unresponsive Zigbee/Wi-Fi device) is
silently skipped by HA's core service dispatch, with no trace error, log
warning, or other signal - there's nothing for `classification.py` to
classify. This sensor takes a different, proactive approach instead of
waiting for an automation to run and fail:

1. Find every entity referenced by your automations, scripts, and scenes -
   directly (`entities_in_automation` / `entities_in_script` /
   `entities_in_scene`), or, for automations/scripts, via a
   `device_id`/`area_id` target resolved through the entity/device
   registries too (the same functions behind HA's own "Related" tab in
   the automation/script editor). Scenes are a flat `entities:` mapping
   with no action sequence and no device/area targets to resolve, so
   `entities_in_scene` alone already covers them completely.
2. Watch those entities' state
3. If one has been continuously `unavailable` (not `unknown` - see below)
   for longer than a configurable threshold, flag it

Implemented in `linked_entities.py` (pure map-building/decision logic, no
HA imports, unit tested) and `linked_entities_coordinator.py` (the
HA-touching half: registry lookups, state-change tracking, per-entity
timers). Fully independent of `coordinator.py`/`classification.py` - no
shared state, so this feature can't regress the existing trace-based
sensor.

**Only `unavailable`, not `unknown`, counts.** `unknown` is often a
legitimate state (right after HA restart, a template with no value yet)
rather than a sign of a broken device; treating it as unavailable-like
would risk false positives and undermine trust in the sensor, the same
concern the trace-based sensor's classification already has to manage.

**Ignored entities** are dropped at reference-map build time, so they're
never tracked or timed, and adding an already-flagged entity to the list
unflags it on the next rebuild (options changes reload the config entry,
which rebuilds from scratch - see `_async_options_updated` in
`__init__.py`).

**"Skip automations that are turned off"**: off by default, to preserve
prior behaviour. Off by default: a turned-off automation's config is
still fully parseable, so its referenced entities are tracked and can be
flagged just like any other, even though the automation can't actually
run right now and so poses no practical risk while it stays off - useful
if you disable automations seasonally (e.g. winter-only solar/battery
charge-limit automations) and don't want their entities' unavailability
nagging you while unused. Only ever applies to automations, never
scripts or scenes - a script entity's own "off" state means "not
currently running" (idle), not "disabled"; scripts have no
enable/disable concept at all, so filtering them the same way would
incorrectly exclude nearly every script nearly all the time. Scenes have
no on/off state at all (activating one doesn't leave it "on"), so the
concept doesn't even apply. Toggling an automation on/off is picked up
immediately (a dedicated state-change subscription, only active while
this option is on - see `_handle_automation_toggle` in
`linked_entities_coordinator.py`), not just on the next periodic
rebuild.

**Excluded labels**: uses HA's own label feature (Settings → Areas,
labels & zones → Labels) rather than a hand-picked entity_id list: label
whatever should be left alone - an automation, an entity, or a whole
device (excludes all of that device's entities, not just individually
labeled ones) - and pick that label in Options. A labeled automation is
skipped entirely by *both* sensors: never flagged by the trace-based
failed-automations sensor even if it errors, and skipped as a
reference-map source here (its referenced entities simply aren't tracked
via it, though still tracked if another, non-excluded
automation/script/scene also references them). A labeled entity or
device is excluded from this sensor the same way an ignored entity is.
Label changes are picked up on the next periodic rebuild or
`rebuild_linked_entities` service call, not immediately - same as a
script content edit, see below; a failed-automations sensor check
re-evaluates an automation's labels fresh on every trigger, so no reload
is needed there.

**Keeping the reference map fresh**: rebuilt on automation reload
(`automation_reloaded` event), on automation/script/scene add/rename/
delete (`entity_registry_updated`), on an automation being turned on/off
(only while the toggle above is on), on HA startup, and as a periodic
safety net every 20 minutes - the last one exists because there is no
equivalent `script_reloaded`/`scene_reloaded` event, so a script's or
scene's *content* changing (without adding/removing the entity itself)
has no dedicated event to react to. Call the
`automation_monitor.rebuild_linked_entities` service for an immediate
rebuild instead of waiting up to 20 minutes after a script or scene edit.

Templated `entity_id`/`device_id`/`area_id` targets are not resolvable
statically - same limitation Watchman already has for entity-existence
checks, just for availability instead of existence. Like the trace access
above, this relies on internal-ish HA behavior (event names, registry
helper functions) that isn't a fully documented stable API.

### Per-entity streak threshold override

Matched via direct `entity_id` references only (an automation's
triggers/conditions/actions), not via device/area targets - a deliberate
scope cut, documented in `coordinator.py`'s
`_effective_streak_threshold` docstring. If an automation touches
several entities with different overrides, the *highest* one wins
(treated as tolerantly as the flakiest entity it touches).

### Ignored error texts

Checked in `coordinator.py::_async_process_trigger`, right after
`_build_error_message` and before the streak counter is touched - a
match causes an immediate `return`, so the streak, `.data`, and the
Logbook events (see below) are all left completely untouched, as if this
particular run never happened. Deliberately checked *before* the streak
increment (not after, with an undo) - `error_message`/`error_step` used
to only be computed once a run was already known to cross the threshold;
moving that computation earlier (harmless, since `_build_error_message`
is a pure static method with no side effects) keeps the control flow a
single straight line instead of a compute-then-maybe-rollback shape.

Plain, case-sensitive substring containment (`text in error_message`),
not regex - matches how the feature was requested (a real user wanted to
paste in the *exact* wording of one known-flaky error, not write a
pattern). Narrower than `excluded_automations`/`excluded_labels`: those
drop the automation/entity from monitoring entirely regardless of *why*
it failed, whereas this only suppresses one specific kind of error -
other, different failures on the same automation are still caught and
flagged normally.

## Repairs issues internals

Shows up under Settings → System → Repairs - admin-only, which is the
whole reason this exists in its current form. An earlier version of this
used `persistent_notification.async_create()` (HA's bell-icon
notification) instead, but that component has no per-user/admin
targeting at all - verified against the real HA core source
(`homeassistant/components/persistent_notification/__init__.py`): it
broadcasts globally to every connected client via a shared dispatcher, no
targeting parameter exists anywhere in its API. A real user reported
non-admin household members seeing these, which isn't appropriate for
what's fundamentally an admin/maintenance concern - Repairs is admin-only
by design instead, so this was migrated over entirely.

Placeholder values (name, error message, formatted timestamp, links) are
built by pure, unit-tested functions in `issues.py`
(`failed_automation_placeholders` / `linked_entity_placeholders`);
`__init__.py` wires them to each coordinator via
`coordinator.async_add_listener` and calls
`homeassistant.helpers.issue_registry`'s `async_create_issue`/
`async_delete_issue`. Actual cleanup on integration removal lives in
`async_remove_entry`, which HA only calls on a genuine delete - not
`async_unload_entry`, which also runs on every reload (an options save
included) - same "don't wipe on a routine reload" lesson the old
notification version of this learned the hard way, still applies here.

### What "Ignorieren"/"Ignore" on an issue actually does

Asked by **Micha**. This is HA's own native Repairs button, not
something this integration builds: verified against the real HA core
source (`homeassistant/helpers/issue_registry.py`,
`homeassistant/components/repairs/websocket_api.py`) it sets a
`dismissed_version` marker, which hides the issue from the main Repairs
list without deleting anything. It's closer to "OK, seen it, hide it for
now" than a permanent dismissal: this integration updates an
already-open issue in place on every subsequent failure (fresh error
message/timestamp), and that update path explicitly preserves
`dismissed_version` - so an ignored issue *stays* ignored through
repeated failures of the same problem. It only reappears once the issue
is actually deleted and later re-created from scratch - i.e. the
automation/entity has to genuinely recover at least once before failing
again.

## Language mechanism

Two separate mechanisms, both covered:

- **Entity names, the Options dialog, and Repairs issue titles/
  descriptions** all go through HA's own built-in translation system
  (`strings.json` + `translations/<lang>.json`) - the standard mechanism
  every HA integration uses.
- **Repairs issues** are the one part generated at runtime from live
  data (an error message, a timestamp, a link) rather than being purely
  static form text - HA's `translation_key` + `translation_placeholders`
  mechanism (see `issues.py`) covers that too, via `{placeholder}`
  tokens in the translated template. This replaced an earlier version of
  this project (the old persistent-notification approach) that needed a
  hand-rolled per-language string table instead, since
  persistent-notification text had no comparable mechanism to hook into
  - that workaround is gone.

Adding another language: add `translations/<lang>.json` mirroring
`translations/en.json` - covers entity names, the Options dialog, and the
`issues` section together, no separate mechanism to update. Not yet
verified live with `hass.config.language` actually set to `de` on a
running instance.
