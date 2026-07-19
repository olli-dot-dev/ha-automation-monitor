# Automation Monitor

<p align="center">
  <img src="custom_components/automation_monitor/brand/logo.png" width="96" alt="Automation Monitor logo">
</p>

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/olli-dot-dev/ha-automation-monitor)](https://github.com/olli-dot-dev/ha-automation-monitor/releases)
![Maintenance](https://img.shields.io/maintenance/yes/2026.svg)

A lightweight Home Assistant custom integration (HACS) with two structured
sensors: one detects failed automation runs from trace data, the other
proactively flags entities referenced by your automations/scripts that are
stuck `unavailable` - a failure mode the trace-based sensor cannot see at
all (see Linked entity unavailability detection). Optional persistent
notifications, toggled independently per sensor (see Persistent
notifications) - no dashboard card, no retention logic beyond that.
Detection and structured exposure is the focus; how you display or act on
the data (Markdown card, `auto-entities`, your own automations, ...) is
up to you.

<!-- TODO: add a screenshot once available, e.g. of the Developer Tools
"States" view for sensor.failed_automations, or a Markdown card built from
the Recommended display example below:
![Automation Monitor screenshot](assets/screenshot.png)
-->

See [CHANGELOG.md](CHANGELOG.md) for release notes.

Complementary to [Watchman](https://github.com/dummylabs/thewatchman),
which checks *statically* for missing entities/services in your config.
Automation Monitor covers the other half: *runtime* errors when an
automation actually runs.

## In plain terms

Two different things can go wrong with an automation, and this
integration watches for both:

1. **"It ran, and it broke."** Your automation actually fired, and
   something inside it went wrong (a light didn't respond, a step threw
   an error). Like turning a car's key and hearing the engine cough.
   → watched by **`sensor.failed_automations`**.
2. **"It's already broken, waiting to happen."** A light, switch, or
   other device your automation *uses* has gone offline - but no
   automation has tried to use it yet, so nothing has failed *yet*.
   Like a flat tire on a parked car: broken right now, you just haven't
   driven anywhere to notice.
   → watched by **`sensor.linked_entities_unavailable`**.

Each is its own sensor, and they run completely independently of each
other - use either one on its own, or both together:

| Sensor | Catches | Example |
| --- | --- | --- |
| `sensor.failed_automations` | An automation ran and something in it errored out | A script step calls a service that fails |
| `sensor.linked_entities_unavailable` | A device an automation *would use* is offline, whether or not that automation has run | A Zigbee light drops off the network |

Both show up as data (a sensor with a list), not as a fix. This
integration never changes anything in your house - it only watches and
reports. What you do with that report (a notification, a dashboard, a
follow-up automation) is entirely up to you.

**What this can't do:** it can't catch a mistake *before* you save it
(a typo'd device name, a setting that doesn't exist) - that's a config
check, and HA's own Settings → System → Repairs (or the separate
Watchman add-on) already does that well. This integration only speaks
up once something has actually gone wrong, or is already sitting broken.

## Why not just use Watchman / HA's built-in Repairs?

Home Assistant has gained its own native config validation over the last
couple of years: Settings → System → Repairs will flag things like an
automation action referencing a service that doesn't exist at all (e.g.
a typo'd service name). That's **static** validation - the same category
Watchman covers - and it can be checked without ever running the
automation.

This matters because it's easy to pick a misleading test case: calling a
genuinely nonexistent service (`light.this_service_does_not_exist`, one
of the scenarios validated during development) gets caught by both HA's
native Repairs *and* this integration. That
overlap is real but narrow - it's the one failure mode in this project's
own test suite that HA already catches on its own, without needing this
integration at all.

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

Also, structurally: Repairs is a one-off, UI-only, per-issue list tied
to the *config* (dismiss it and it's gone until the same issue recurs).
It's not queryable as sensor attributes, can't be templated or put on a
dashboard, and doesn't reflect "is this currently failing right now,
and since when" the way this integration's sensor does - it clears
automatically on the next successful run.

## Requirements

- Home Assistant 2024.1 or newer
- [HACS](https://hacs.xyz/) installed (for the HACS installation method below;
  not required for a manual install)

## Installation

Not yet published to the default HACS store - install via a custom
repository for now.

### One-click (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=olli-dot-dev&repository=ha-automation-monitor&category=integration)

Click the badge above to add this repository to HACS directly - it handles adding the custom repository and finding the integration for you. Then click **Download** and restart Home Assistant.

### Via HACS (custom repository, manual)

1. Open HACS in your Home Assistant sidebar
2. Go to **⋮ → Custom repositories**
3. Add `https://github.com/olli-dot-dev/ha-automation-monitor` with category **Integration**
4. Find **Automation Monitor** in the HACS integration list and click **Download**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/automation_monitor` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

## Setup

After installation and restart:

1. Go to **Settings → Devices & Services → + Add Integration**
2. Search for **Automation Monitor** and click it
3. Confirm - no configuration needed to enable it

Both `sensor.failed_automations` and `sensor.linked_entities_unavailable`
appear immediately. To change the linked-entities threshold afterward,
open the integration's entry and click **Configure** (see Linked entity
unavailability detection).

## Usage

Both sensors work passively once installed - there's nothing to trigger
manually day to day:

- **`sensor.failed_automations`** reflects currently-failing automations in
  its `automations` attribute; see Recommended display / Recommended
  notification automation below for ready-to-use ways to surface it on a
  dashboard or as a notification
- **`sensor.linked_entities_unavailable`** reflects entities referenced by
  your automations/scripts that have been unreachable past the configured
  threshold, in its `entities` attribute
- Call `automation_monitor.reset` to clear a stuck failure entry without
  waiting for a restart or a successful re-run (see Actions)
- Call `automation_monitor.rebuild_linked_entities` right after editing a
  script's content, to pick up the change immediately instead of waiting
  for the periodic safety-net rebuild (see Actions)
- **A Home Assistant restart resets both sensors** - no persistence
  across restarts, by design. `sensor.failed_automations` starts empty
  since it's purely event-driven (only reacts to a fresh
  `automation_triggered` event, not to whatever was already broken
  before the restart). `sensor.linked_entities_unavailable` re-derives
  its state from scratch too, and in practice most entities get a fresh
  `last_changed` timestamp from their own integration when HA
  reinitializes at startup - so even a device that's been broken for
  days needs to wait out the full threshold *again* after a restart
  before it's flagged (and notified about) once more

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

**Entities can be ignored** via the same Options dialog - an entity picker
(multi-select) lets you exclude specific entities from this check
entirely, e.g. a device that's expected to be offline for long stretches
on purpose. Ignored entities are dropped at reference-map build time, so
they're never tracked or timed, and adding an already-flagged entity to
the list unflags it on the next rebuild (options changes reload the
config entry, which rebuilds from scratch - see `_async_options_updated`
in `__init__.py`).

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

## Persistent notifications

Two independent toggles in the integration's Options (Settings → Devices
& Services → Automation Monitor → Configure), off by default: one for
`sensor.failed_automations`, one for `sensor.linked_entities_unavailable`.
Enable either, both, or neither - they don't affect each other.

Each enabled sensor gets exactly one persistent notification (HA's
built-in in-UI notification, shown under the bell icon - **not** a push
notification to your phone) under a fixed ID, so it's always updated in
place rather than piling up a new card every time something changes:

- While the sensor has anything to report, the notification lists every
  currently-affected entity/automation, one line each - each name is a
  clickable Markdown link, which HA's frontend opens in-app rather than
  reloading the page:
  - A **failed automation** links to its editor
    (`/config/automation/edit/<unique_id>`) - the actionable next step is
    to go fix it. Falls back to the entity settings link below if the
    automation's unique_id can't be resolved for some reason.
  - An **unavailable linked entity** links to its **device** page
    (`/config/devices/device/<device_id>`) - the route pattern itself
    is confirmed correct (the user copied a real, working URL in exactly
    this shape straight from their own browser), though clicking the
    link *from inside the notification* hasn't been done yet. Entities
    with no device (helpers, template entities, ...) fall back to the
    entity settings page (`/config/entities/entity/<entity_id>`) instead
    - **that fallback route is this project's best guess, not
    independently verified live**. Either way, if known, the entity link
    is followed by "used by" links to every automation/script that
    references it
    (`/config/automation/edit/...` or `/config/script/edit/...`, each
    falling back to plain unlinked text if its own unique_id can't be
    resolved). The `unavailable since` timestamp is formatted as
    `YYYY-MM-DD HH:MM` in the local timezone, instead of the raw
    ISO-8601 UTC string it's stored as internally - fixed after an
    earlier version of this showed the correct-looking but actually
    unconverted UTC clock value (e.g. `11:10` shown when it should have
    read `13:10` local). Uses the *system* timezone (`.astimezone()`
    with no argument, since `notifications.py` deliberately has no HA
    imports and can't read `hass.config.time_zone` directly) - correct
    as long as the machine's OS timezone matches HA's configured one,
    which holds for a typical single-purpose HAOS install.
- Each entity in the `sensor.linked_entities_unavailable` notification
  also shows its raw `entity_id` in copyable inline-code formatting
  (e.g. `` `light.hallway` ``) right next to its name, and the
  notification ends with a link to the integration's own settings
  (`/config/integrations/integration/automation_monitor`) plus a hint to
  copy an entity_id above and paste it in - for adding one of the listed
  entities to the ignore-list (see Linked entity unavailability
  detection). This only saves the navigation and the typing, not the
  picking-the-entity step itself - HA's options flow has no mechanism to
  pre-fill a field from a link, so the entity still has to be selected
  (pasting the entity_id into the picker's search box works) and saved
  manually once there. Both are absent when the notification is empty.
- Once the sensor goes back to empty (nothing failed / nothing
  unavailable), the notification is automatically dismissed
- Turning a toggle off dismisses that sensor's notification immediately,
  even if it was currently showing something
- Saving *any* option (even an unrelated one, like the threshold) does
  **not** clear an already-shown notification - only a genuine removal of
  the integration does (see below). An earlier version of this got that
  wrong: it dismissed both notifications on every config-entry reload,
  which options changes also trigger, so saving the options form looked
  like it had silently cleared real, still-true failures - it hadn't,
  the notification just hadn't been told to redraw itself yet

Message text is built by pure, unit-tested functions in `notifications.py`
(`build_failed_automations_message` / `build_linked_entities_message`);
`__init__.py` wires them to each coordinator via
`coordinator.async_add_listener` and calls
`persistent_notification.async_create`/`async_dismiss`. Actual dismissal
on integration removal lives in `async_remove_entry`, which HA only calls
on a genuine delete - not `async_unload_entry`, which also runs on every
reload (see the point above) - live-verified.

This is meant for a quick, always-on-if-you-want-it status card, not a
push alert - for that, see Recommended notification automation below,
which you can run alongside these toggles (they don't conflict; one
updates a persistent card, the other fires a one-off notification per new
failure).

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

Same pattern for the linked-entities sensor, using its `entities` attribute:

```yaml
type: markdown
content: >
  {% for e in state_attr('sensor.linked_entities_unavailable', 'entities') %}
  **{{ e.name }}** - unavailable since {{ e.unavailable_since }}
  Used by: {{ e.referenced_by | join(', ') }}

  {% endfor %}
```

## Recommended notification automation (documentation only, not part of the integration)

Want a push notification instead of (or alongside) the built-in
persistent-notification toggles from Persistent notifications above? Use
this. Fires only when the failure count *increases* (a genuinely new failure),
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

## Contributing

1. Fork the repository
2. Drop `custom_components/automation_monitor` into your HA `config/custom_components/`
3. Restart Home Assistant after changes to any `.py` file - reloading the
   integration from Settings → Devices & Services is **not** enough, since
   a reload re-runs the already-imported module rather than re-reading it
   from disk
4. Run `pytest` (see above) before opening a PR
5. Open a pull request

## License

[MIT](LICENSE)
