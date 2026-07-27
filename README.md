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
all (see Linked entity unavailability detection). Optional Repairs issues,
toggled independently per sensor (see Repairs issues) - no dashboard card,
no retention logic beyond that. Detection and structured exposure is the
focus; how you display or act on the data (Markdown card, `auto-entities`,
your own automations, ...) is up to you. A third entity,
`update.automation_monitor`, applies the same detect-and-expose approach
to the integration itself (see Update detection).

![Rendered Markdown card showing one failed automation](assets/recommended-display-detailed.png)

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

Also, structurally: HA's *own* static Repairs issues are tied to the
*config* and one-off - dismiss one and it's gone until the same issue
recurs, and none of it is queryable as sensor attributes, templatable, or
put on a dashboard the way this integration's sensors are. The sensors
are always the source of truth here, restart-independent of whatever's
shown in Repairs.

This project *does* optionally publish its own findings to Repairs too
(see Repairs issues) - but on its own terms: one issue per
currently-failed automation / currently-unavailable entity, created and
automatically deleted in lockstep with the sensor data itself, not a
one-off static check. That's a deliberate choice for admin-only
visibility (Repairs, unlike a persistent notification, only shows to
admin users) rather than a replacement for what the sensors already do.

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
appear immediately. To change any setting afterward, open the
integration's entry and click **Configure** (see Configuration).

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

**Classifying a run as a failure doesn't necessarily flag it right
away.** A second, independent setting - the failure streak threshold
(default 1, i.e. flag on the very first failure) - decides how many
*consecutive* failures an automation needs before `sensor.failed_automations`
actually reports it, with an optional per-entity override for
particularly flaky devices. See Configuration.

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

**Threshold is configurable** (see Configuration), default 15 minutes -
short enough to catch a stuck device promptly, long enough to not fire on
routine reconnect blips.

**Entities can be ignored** (see Configuration) - excludes specific
entities from this check entirely, e.g. a device that's expected to be
offline for long stretches on purpose. Ignored entities are dropped at
reference-map build time, so they're never tracked or timed, and adding
an already-flagged entity to the list unflags it on the next rebuild
(options changes reload the config entry, which rebuilds from scratch -
see `_async_options_updated` in `__init__.py`).

**Automations that are turned off can be skipped entirely** via a toggle
(see Configuration), off by default to preserve prior behaviour. Off by
default: a turned-off automation's config is still fully parseable, so its
referenced entities are tracked and can be flagged just like any other,
even though the automation can't actually run right now and so poses no
practical risk while it stays off - useful if you disable automations
seasonally (e.g. winter-only solar/battery charge-limit automations) and
don't want their entities' unavailability nagging you while unused. Only
ever applies to automations, never scripts - a script entity's own "off"
state means "not currently running" (idle), not "disabled"; scripts have
no enable/disable concept at all, so filtering them the same way would
incorrectly exclude nearly every script nearly all the time. Toggling an
automation on/off is picked up immediately (a dedicated state-change
subscription, only active while this option is on - see
`_handle_automation_toggle` in `linked_entities_coordinator.py`), not
just on the next periodic rebuild.

**Labels can exclude automations, entities and devices** (see
Configuration), using HA's own label feature (Settings → Areas, labels &
zones → Labels) rather than a hand-picked entity_id list: label whatever
should be left alone -
an automation, an entity, or a whole device (excludes all of that
device's entities, not just individually labeled ones) - and pick that
label here. A labeled automation is skipped entirely by *both* sensors:
never flagged by the trace-based failed-automations sensor even if it
errors, and skipped as a reference-map source here (its referenced
entities simply aren't tracked via it, though still tracked if another,
non-excluded automation/script also references them). A labeled entity
or device is excluded from this sensor the same way an ignored entity is
(see above). Label changes are picked up on the next periodic rebuild or
`rebuild_linked_entities` service call, not immediately - same as a
script content edit, see below; a failed-automations sensor check
re-evaluates an automation's labels fresh on every trigger, so no reload
is needed there.

**Keeping the reference map fresh**: rebuilt on automation reload
(`automation_reloaded` event), on automation/script add/rename/delete
(`entity_registry_updated`), on an automation being turned on/off (only
while the toggle above is on), on HA startup, and as a periodic safety
net every 20 minutes - the last one exists because there is no
equivalent `script_reloaded` event, so a script's *content* changing
(without adding/removing the script entity itself) has no dedicated
event to react to. Call the `automation_monitor.rebuild_linked_entities`
service for an immediate rebuild instead of waiting up to 20 minutes
after a script edit.

Templated `entity_id`/`device_id`/`area_id` targets are not resolvable
statically - same limitation Watchman already has for entity-existence
checks, just for availability instead of existence. Like the trace access
above, this relies on internal-ish HA behavior (event names, registry
helper functions) that isn't a fully documented stable API.

## Configuration

Click **Configure** on the integration's entry (Settings → Devices &
Services → Automation Monitor) to open a three-way menu:

![Options menu: General settings, Entities, Automations](assets/options-menu.png)

### General settings

Settings that aren't clearly entity- or automation-specific: the
`linked_entities_unavailable` threshold (see Linked entity unavailability
detection), excluded labels (affects *both* sensors at once - see below
for how that differs from the entity-/automation-specific settings),
whether to open a Repairs issue per sensor (see Repairs issues), and the
global failure streak threshold (see Failure classification).

![General settings screen](assets/options-general.png)

### Entities

Entity-level settings - picked here, values entered on a second screen
since HA's selectors have no single widget for "entity + number":

![Entities settings screen](assets/options-entities.png)

- **Ignored entities** - only affects `sensor.linked_entities_unavailable`
  (see Linked entity unavailability detection)
- **Entities with an individual streak threshold** - only affects
  `sensor.failed_automations`: overrides the global default from General
  settings for automations that touch this specific entity. Requested by
  a real user (forum feedback, 2026-07-27) with a Zigbee mesh that
  occasionally times out on the first attempt but succeeds on retry - a
  specific flaky device can be given more tolerance than the rest, rather
  than raising the threshold for every automation. Matched via direct
  `entity_id` references only (an automation's triggers/conditions/
  actions), not via device/area targets - a deliberate scope cut,
  documented in `coordinator.py`'s `_effective_streak_threshold`
  docstring. If an automation touches several entities with different
  overrides, the *highest* one wins (treated as tolerantly as the flakiest
  entity it touches).

### Automations

Automation-level settings, same picker-then-detail-screen shape as
Entities above:

![Automations settings screen](assets/options-automations.png)

- **Skip automations that are turned off** - only affects
  `sensor.linked_entities_unavailable` (see Linked entity unavailability
  detection)
- **Automations with individual per-sensor exclusion** - pick automations
  here, then choose on the next screen which sensor(s) each one should be
  excluded from. Unlike an excluded label (General settings, always
  excludes from *both* sensors), this lets an automation be excluded from
  just one - e.g. a known-flaky automation excluded from
  `sensor.failed_automations` while its referenced entities are still
  tracked by `sensor.linked_entities_unavailable` (other automations may
  reference the same entities).

## Repairs issues

Two independent toggles under General settings (see Configuration), off
by default: one for `sensor.failed_automations`, one for
`sensor.linked_entities_unavailable`. Enable either, both, or neither -
they don't affect each other.

Shows up under **Settings → System → Repairs** - admin-only, which is the
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

![Repairs overview: one open issue reported by Automation Monitor](assets/repairs-overview.png)

One issue per currently-failed automation / currently-unavailable linked
entity - not one combined card the way the old notification worked.
Matches how the Repairs page already presents multiple issues as
separate, individually-dismissible rows:

- Created the moment an automation/entity is flagged, updated in place on
  every subsequent failure (fresh error message/timestamp - the issue_id
  stays the same, so it's the same row, not a new one piling up), and
  automatically deleted once it resolves: a successful run, the entity
  becoming available again, or the `reset` action clearing it (see
  Actions).
- Opening an issue shows the full detail, including a clickable link
  straight to the automation editor (or, for a linked entity, its device
  page) and, for a linked entity, which automation(s)/script(s)
  reference it:

  ![Repairs issue detail, with a clickable link to the automation editor](assets/repairs-detail.png)

- Turning a toggle off clears every open issue for that sensor
  immediately, even if some were currently open.
- Saving *any* option (even an unrelated one, like the threshold) does
  **not** clear already-open issues that are still genuinely true -
  each sync only touches issues under its own sensor's prefix, diffing
  against what the sensor currently reports rather than clearing
  everything and starting over.

Severity is always `warning` (not `critical`) - a real problem worth
looking at, but not something that took HA itself down. Detection only,
same as the sensors: no "fix" flow is offered (`is_fixable=False`), the
issue is just a pointer to the same underlying problem the sensor
already tracks - go use the editor link, fix the automation/device, and
the issue clears itself once resolved.

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

This is meant for a quick, always-on-if-you-want-it admin view, not a
push alert to your phone - for that, see Recommended notification
automation below, which you can run alongside these toggles (they don't
conflict; one opens a Repairs entry, the other fires a one-off push
notification per new failure).

## Language

English, German, French and Spanish (`en`/`de`/`fr`/`es`) so far - German
was added first, requested by a German-speaking user who found the
(English-only, at the time) notifications hard to follow. Automatically
follows HA's own system language (Settings → System → General →
Language, `hass.config.language`) - nothing to configure. Falls back to
English for any other language.

Entity names, the Options dialog, and Repairs issue titles/descriptions
all go through HA's own built-in translation system (`strings.json` +
`translations/<lang>.json`) - the standard mechanism every HA integration
uses, so nothing special here. Repairs issues are the one part that's
generated at runtime from live data (an error message, a timestamp, a
link) rather than being purely static form text - HA's `translation_key`
+ `translation_placeholders` mechanism (see `issues.py`) covers that too,
via `{placeholder}` tokens in the translated template. This replaced an
earlier version of this project (the old persistent-notification
approach, see Repairs issues) that needed a hand-rolled per-language
string table instead, since persistent-notification text had no
comparable mechanism to hook into - that workaround is gone.
Entity/automation *names* and error messages themselves are still never
translated (they're your own data, or another integration's error text),
only the surrounding template words.

Adding another language: add `translations/<lang>.json` mirroring
`translations/en.json` - covers entity names, the Options dialog, and the
`issues` section together, no separate mechanism to update. Not yet
verified live with `hass.config.language` actually set to `de` on a
running instance.

## Actions

`automation_monitor.reset` clears currently tracked failures without
waiting for a restart or for each automation to succeed again - also
resets its consecutive-failure streak count (see Configuration /
Failure classification) back to zero, so it doesn't immediately re-flag
itself on the next failure:

- No target: clears all currently tracked failures.
- `entity_id: automation.xyz`: clears only that automation's entry, if present.

`automation_monitor.rebuild_linked_entities` immediately rebuilds the
automation/script → referenced-entity map used by the linked-entities
sensor, instead of waiting for the periodic 20-minute safety-net rebuild.
No target/fields - useful right after editing a script's content (see
Linked entity unavailability detection for why scripts specifically need
this).

## Update detection

`update.automation_monitor` checks this repo's GitHub Releases every 12
hours (plus once immediately on setup/restart) and reports whether a
newer version is available, with a direct link to the release notes.
Detection only - it never installs anything itself; updating is still
done the normal way (HACS, or a manual copy + restart).

This exists because the integration isn't on the default HACS store yet
(see Installation) - HACS only creates its own per-repository update
entity for integrations it fully manages that way, not for ones added as
a custom repository. If GitHub can't be reached (or the request is
rate-limited), the entity reports itself `unavailable` rather than
silently claiming "up to date".

Want a push notification the moment an update becomes available, rather
than checking the entity yourself? Same pattern as the failed-automations
example above:

```yaml
triggers:
  - trigger: state
    entity_id: update.automation_monitor
    to: "on"
actions:
  - action: notify.notify  # replace with your actual notify target
    data:
      title: "Automation Monitor update available"
      message: >
        {{ state_attr('update.automation_monitor', 'latest_version') }} is out.
        {{ state_attr('update.automation_monitor', 'release_url') }}
```

## Recommended display (documentation only, not part of the integration)

```yaml
type: markdown
content: >
  {% for a in state_attr('sensor.failed_automations', 'automations') %}
  **{{ a.name }}** - {{ a.last_error_time }}
  {{ a.error_message }}

  {% endfor %}
```

A more detailed variant, shared by community member ArnaudFeld
([smarterkram.de forum](https://community.smarterkram.de/t/automation-monitor-neue-hacs-integration-fuer-fehlgeschlagene-automationen/551/8)) -
a heading with the current failure count, one block per failed automation
(name, entity_id, error step, formatted timestamp, error message), and a
success message when there's nothing to report:

```yaml
type: markdown
content: >
  {% set monitor_entity = 'sensor.failed_automations' %}
  {% set failed_list = state_attr(monitor_entity, 'automations') %}
  {% if failed_list is defined and failed_list and failed_list | length > 0 %}
    # 🚨 Fehlgeschlagene Automatisierungen ({{ failed_list | length }})

    {% for item in failed_list %}
      ### ❌ {{ item.name }}
      * **Entität:** `{{ item.entity_id }}`
      * **Fehler-Schritt:** `{{ item.error_step }}`
      * **Zeitpunkt:** {{ as_timestamp(item.last_error_time) | timestamp_custom('%d.%m.%Y um %H:%M Uhr') }}

      > **Fehlermeldung:**
      > `{{ item.error_message }}`

      ---
    {% endfor %}
  {% else %}
    # ✅ Automatisierungs-Monitor

    🎉 **Alles super!** Aktuell wurden keine fehlerhaften Automatisierungen erfasst.
  {% endif %}
```

![Rendered Markdown card showing one failed automation, using the detailed variant above](assets/recommended-display-detailed.png)

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

Want a push notification to your phone instead of (or alongside) the
built-in Repairs-issue toggles from Repairs issues above? Use this - a
Repairs issue is admin-only and lives in Settings → System → Repairs,
not something that pushes to your phone. Fires only when the failure
count *increases* (a genuinely new failure),
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
