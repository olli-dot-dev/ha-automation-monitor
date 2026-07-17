# Automation Monitor

A lightweight Home Assistant custom integration (HACS) that detects failed
automation runs and exposes them as a structured sensor. No notifications,
no dashboard card, no retention logic - detection and structured exposure
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

- A service call to an entity that exists, but whose device is
  temporarily offline/unresponsive (Zigbee/Wi-Fi dropout, timeout)
- A template that's syntactically valid but hits `None` or a missing key
  at runtime, depending on live state
- A deliberate `stop: ... error: true` - not a config problem at all, so
  Repairs never sees it (verified live, see Testing notes)
- A cloud-integration service call that fails due to that service's own
  backend/network issues

Also, structurally: Repairs is a one-off, UI-only, per-issue list tied
to the *config* (dismiss it and it's gone until the same issue recurs).
It's not queryable as sensor attributes, can't be templated or put on a
dashboard, and doesn't reflect "is this currently failing right now,
and since when" the way this integration's sensor does - it clears
automatically on the next successful run.

## Status

Core logic implemented and validated live against a real HA 2026.7.1
instance with all four cases from the Testing notes below (error,
mid-sequence condition action, `stop: ... error: true`, `mode: single`
re-trigger) - all four classify correctly. Not yet released via HACS;
still MVP-scope only (no persistence across restarts, no notifications).

## Scope (MVP)

**In scope**
- Detecting failed automation runs from trace data
- One collection sensor with an attribute list of all currently failed automations
- Clean separation of "real error" vs. "intended stop behaviour"
- Config flow to enable (no options needed for MVP)

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

## Architecture

- `DataUpdateCoordinator`-based, but event-driven instead of polling
  (updates on every `automation_triggered` event, no fixed interval)
- Config entry with no external connection - pure event-listener integration
- `iot_class: local_push`

```
custom_components/automation_monitor/
├── __init__.py          # setup, event listener registration
├── config_flow.py       # minimal config flow (enable only)
├── coordinator.py        # event handling, trace fetch, classification
├── classification.py     # pure classification rules (no HA imports, unit tested)
├── sensor.py              # collection sensor
└── manifest.json
```

## Data model

One sensor:

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

## Actions

`automation_monitor.reset` clears currently tracked failures without
waiting for a restart or for each automation to succeed again:

- No target: clears all currently tracked failures.
- `entity_id: automation.xyz`: clears only that automation's entry, if present.

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
        - action: notify.notify
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

## Development

```bash
pip install -r requirements_test.txt
pytest
```
