# Automation Monitor

A lightweight Home Assistant custom integration (HACS) with two structured
sensors: one detects failed automation runs from trace data, the other
proactively flags entities referenced by your automations/scripts that are
stuck `unavailable` - a failure mode the trace-based sensor cannot see at
all (see Linked entity unavailability detection). No notifications, no
dashboard card, no retention logic - detection and structured exposure
only. How you display or act on the data (Markdown card, `auto-entities`,
your own automations, ...) is up to you.

Complementary to [Watchman](https://github.com/dummylabs/thewatchman),
which checks *statically* for missing entities/services in your config.
Automation Monitor covers the other half: *runtime* errors when an
automation actually runs.

## Why not just use Watchman / HA's built-in Repairs?

Home Assistant has gained its own native config validation over the last
couple of years: Settings → System → Repairs will flag things like an
automation action referencing a service that doesn't exist at all (e.g.
a typo'd service name). That's **static** validation - the same category
Watchman covers - and it can be checked without ever running the
automation.

This matters because it's easy to pick a misleading test case: calling a
genuinely nonexistent service (`light.this_service_does_not_exist`, one
of the four scenarios validated during development, see Testing notes)
gets caught by both HA's native Repairs *and* this integration. That
overlap is real but narrow - it's the one failure mode in this project's
own test suite that HA already catches on its own, without needing this
integration at all.

Where Automation Monitor is the *only* thing that catches the problem -
because the config is perfectly valid and the failure only exists at
runtime:

- A template that's syntactically valid but hits `None` or a missing key
  at runtime, depending on live state
- A deliberate `stop: ... error: true` - not a config problem at all, so
  Repairs never sees it (verified live, see Testing notes)
- A cloud-integration service call that fails due to that service's own
  backend/network issues, *provided* the integration actually raises on
  failure instead of swallowing it

Also, structurally: Repairs is a one-off, UI-only, per-issue list tied
to the *config* (dismiss it and it's gone until the same issue recurs).
It's not queryable as sensor attributes, can't be templated or put on a
dashboard, and doesn't reflect "is this currently failing right now,
and since when" the way this integration's sensor does - it clears
automatically on the next successful run.

## Status

Trace-based failure sensor: implemented and validated live against a real
HA 2026.7.1 instance with all four cases from the Testing notes below
(error, mid-sequence condition action, `stop: ... error: true`, `mode:
single` re-trigger) - all four classify correctly.

Linked-entity unavailability sensor: implemented, unit tested, deployed
live without error (entity loads with the expected empty baseline, options
flow renders and saves correctly) - built in response to a real production
incident the trace-based sensor missed entirely. The core new mechanism
(device/area target resolution, and the unavailable→flagged timer path
itself) has not yet been exercised against a real state transition - see
Testing notes.

Not yet released via HACS; still MVP-scope only (no persistence across
restarts, no notifications).

## Scope (MVP)

**In scope**
- Detecting failed automation runs from trace data
- One collection sensor with an attribute list of all currently failed automations
- Clean separation of "real error" vs. "intended stop behaviour"
- Proactively flagging entities referenced by automations/scripts that are
  stuck `unavailable`, independent of whether the automation has actually
  run (second sensor, see Linked entity unavailability detection)
- Config flow to enable, plus an options flow for the unavailability threshold

**Explicitly out of scope for now** (possible later)
- Notifications
- A dedicated Lovelace card
- Retention rules (how long a failure stays listed / when it counts as resolved)
- Error categorisation/grouping
- Logbook entries
- Per-automation sensors

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
| `finished` | No | Completed normally (this is what a plain success run reports - HA does **not** use the literal string `"success"`) |

Implemented in `custom_components/automation_monitor/classification.py`,
covered by `tests/test_classification.py`. This is the most
trust-critical part of the integration - false positives make users
ignore the sensor. Validated live against a HA 2026.7.1 test instance
with all four cases from the Testing notes below - all four classify
correctly.

One more live-testing finding: a `mode: single` automation re-triggered
while already running is often rejected by HA *before*
`automation_triggered` even fires (logged as `WARNING ... Already
running`, no trace created) - same "coordinator never sees it" pattern
as the top-level `condition:` block. The `cancelled` script_execution
handling above still matters for other paths (e.g. an automation
explicitly stopped from outside while running), just not for the most
common mode:single case.

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

## Linked entity unavailability detection

A second, independent sensor for a failure mode the trace-based sensor
above cannot see at all: a service call targeting an entity that's
currently `unavailable` (e.g. an unresponsive Zigbee/Wi-Fi device) is
silently skipped by HA's core service dispatch, with no trace error, log
warning, or other signal - there's nothing for `classification.py` to
classify. This sensor takes a different, proactive approach instead of
waiting for an automation to run and fail:

1. Find every entity referenced by your automations and scripts -
   directly, or via a `device_id`/`area_id` target, resolved through the
   entity/device registries (`entities_in_automation` / `entities_in_script`
   and their device/area equivalents - the same functions behind HA's own
   "Related" tab in the automation/script editor)
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

**Threshold is configurable** via the integration's Options (Settings →
Devices & Services → Automation Monitor → Configure), default 15 minutes
- short enough to catch a stuck device promptly, long enough to not fire
on routine reconnect blips.

**Keeping the reference map fresh**: rebuilt on automation reload
(`automation_reloaded` event), on automation/script add/rename/delete
(`entity_registry_updated`), on HA startup, and as a periodic safety net
every 20 minutes - the last one exists because there is no equivalent
`script_reloaded` event, so a script's *content* changing (without
adding/removing the script entity itself) has no dedicated event to react
to. Call the `automation_monitor.rebuild_linked_entities` service for an
immediate rebuild instead of waiting up to 20 minutes after a script edit.

Templated `entity_id`/`device_id`/`area_id` targets are not resolvable
statically - same limitation Watchman already has for entity-existence
checks, just for availability instead of existence. Like the trace access
above, this relies on internal-ish HA behavior (event names, registry
helper functions) that isn't a fully documented stable API - see Testing
notes for what's been checked live so far.

## Architecture

- `DataUpdateCoordinator`-based, but event-driven instead of polling for
  both sensors (the failure sensor updates on every `automation_triggered`
  event; the linked-entities sensor on state changes + per-entity timers,
  see above) - no fixed polling interval for detection itself, aside from
  the documented periodic reference-map safety net
- Config entry with no external connection - pure event-listener integration
- `iot_class: local_push`

```
custom_components/automation_monitor/
├── __init__.py                    # setup, both coordinators, service registration
├── config_flow.py                 # config flow (enable) + options flow (threshold)
├── coordinator.py                  # failure sensor: event handling, trace fetch, classification
├── classification.py               # pure classification rules (no HA imports, unit tested)
├── linked_entities_coordinator.py  # linked-entities sensor: registry lookups, state tracking, timers
├── linked_entities.py              # pure map-building/decision logic (no HA imports, unit tested)
├── sensor.py                       # both collection sensors
└── manifest.json
```

## Data model

Two sensors:

```yaml
sensor.failed_automations
  state: <number of currently failed automations>
  attributes:
    automations:
      - entity_id: automation.garden_watering
        name: "Garden Watering"
        last_error_time: "2026-07-10T14:32:00+02:00"
        error_message: "Unable to find entity switch.garden_pump"
        error_step: "action (step 2)"
```

A successful run of the same automation removes it from the list - no
history/retention in the MVP, this is "current state" only.

```yaml
sensor.linked_entities_unavailable
  state: <number of currently flagged entities>
  attributes:
    entities:
      - entity_id: light.hallway
        name: "Hallway Light"
        state: "unavailable"
        unavailable_since: "2026-07-10T14:32:00+02:00"
        referenced_by:
          - automation.garden_watering
          - script.night_routine
```

An entity is removed from the list as soon as it stops being
`unavailable` - same "current state, no retention" model as the other
sensor. `unavailable_since` is when the entity's state actually last
changed (per HA), not when it crossed the threshold - it can be well
before the entity was flagged.

## Actions

`automation_monitor.reset` clears currently tracked failures without
waiting for a restart or for each automation to succeed again:

- No target: clears all currently tracked failures.
- `entity_id: automation.xyz`: clears only that automation's entry, if present.

`automation_monitor.rebuild_linked_entities` immediately rebuilds the
automation/script → referenced-entity map used by the linked-entities
sensor, instead of waiting for the periodic 20-minute safety-net rebuild.
No target/fields - useful right after editing a script's content (see
Linked entity unavailability detection for why scripts specifically need
this).

## Recommended display (documentation only, not part of the integration)

```yaml
type: markdown
content: >
  {% for a in state_attr('sensor.failed_automations', 'automations') %}
  **{{ a.name }}** - {{ a.last_error_time }}
  {{ a.error_message }}

  {% endfor %}
```

## Recommended notification automation (documentation only, not part of the integration)

Fires only when the failure count *increases* (a genuinely new failure),
not on every state write and not when the count drops from a reset or a
retry succeeding. Diffs the `automations` list against its previous value
so the notification only covers the newly-added entries, even if several
failures land in the same update.

```yaml
triggers:
  - trigger: state
    entity_id: sensor.failed_automations
condition: >
  {{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}
actions:
  - variables:
      previous_ids: >
        {{ trigger.from_state.attributes.automations
           | default([]) | map(attribute='entity_id') | list }}
      new_failures: >
        {{ trigger.to_state.attributes.automations
           | rejectattr('entity_id', 'in', previous_ids) | list }}
  - repeat:
      for_each: "{{ new_failures }}"
      sequence:
        - action: notify.notify  # replace with your actual notify target, e.g. notify.mobile_app_your_phone
          data:
            title: "Automation failed: {{ repeat.item.name }}"
            message: >
              {{ repeat.item.error_message }}
              ({{ repeat.item.error_step }}, {{ repeat.item.last_error_time }})
mode: queued
```

Replace `notify.notify` with a specific notify target (e.g.
`notify.mobile_app_your_phone`). `mode: queued` so that failures arriving
in quick succession each still get their own notification instead of
cancelling one another.

## Open questions

- ~~Delay between `automation_triggered` and trace fetch: fixed timeout or
  poll until the trace reports `running: false`?~~ Resolved: polling
  every 1s up to 60s, see `_async_wait_for_finished_trace` in
  `coordinator.py`. A first attempt at 5s total was too short - live
  testing caught an 8s `delay:` action never getting classified at all.
  Automations that run longer than 60s (e.g. an unbounded
  `wait_for_trigger`) still won't be classified - accepted as a known
  MVP limit rather than polling indefinitely.
- Behaviour on HA restart: keep failures from the previous session
  (needs persistence) or accept a cold start (empty list after restart)?
  **Recommendation: cold start for MVP**, persistence as a later step.
- ~~Automations without a trigger (manual/script-invoked only) - should
  go through the same event, verify explicitly in testing.~~ Resolved:
  yes, all four live test automations below used `triggers: []` and
  were triggered manually via the UI "Run" action - the event fires the
  same way.

## Testing notes

All four verified live against a real HA 2026.7.1 instance:

- ✅ Automation with a deliberate error (e.g. service call on a
  non-existent entity) to verify classification
- ✅ Automation with a *mid-sequence* `condition:` action that fails -
  must **not** appear in the list (most important negative test case; a
  top-level automation `condition:` never even reaches the coordinator,
  see Data source)
- ✅ Automation with `stop: ... error: true` - **should** appear in the
  list; this is the ambiguous `aborted` case, worth extra scrutiny
- ✅ `mode: single` automation re-triggered while still running - must
  **not** count as a failure (in practice HA rejects the second trigger
  before `automation_triggered` even fires, see Failure classification)

**Linked entity unavailability detection** - unit tested (`build_reference_map`,
`decide_transition`, `time_remaining_until_flag`, all pure). Live-verified
against a real HA 2026.7.1 instance:

- ✅ Deploys and loads without error; `sensor.linked_entities_unavailable`
  shows the expected empty baseline (`state: 0`, `entities: []`) when
  nothing tracked is unavailable
- ✅ Options flow opens with the threshold field pre-filled and saves
  correctly (confirms `OptionsFlow.config_entry` is available without
  manually assigning it in `__init__`, see `config_flow.py`)

Still pending - the actual detection mechanism hasn't been exercised
against a real state transition yet:

- ⬜ `entities_in_automation`/`entities_in_script` device/area resolution
  against a real automation using `target: device_id:`/`target: area_id:`
  (a real automation using `target: area_id: kuche` exists on the test
  instance as a candidate)
- ⬜ A real device transitioning to `unavailable` and back, including a
  rapid flap, correctly starting/cancelling the timer and never resetting
  on attribute-only noise
- ⬜ Whether 2026.7.1 has grown a `script_reloaded`-equivalent event (if
  so, the periodic safety-net rebuild could be dropped)

## Development

```bash
pip install -r requirements_test.txt
pytest
```
