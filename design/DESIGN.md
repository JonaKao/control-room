# Control room design

Approved by Jona on 2026-10-17. `mockup.html` and the two screenshots are the reference;
they use sample data. Match their structure and character, not their exact pixels, and
keep every feature the page has today.

## Character

An instrument panel, not a document. Everything important fits on the first screen of a
laptop (1440 × 900); detail opens on demand. Dense but orderly: fine 1 px rules, small
multiples, large numbers where numbers matter, tabular figures for times and counts.

## Layout

- **Left rail (≈264 px):** brand mark and name; a strip of four headline numbers for the
  whole workspace (need you, working, finished, first-try rate); projects grouped by
  state (needs you, working, finished, not started). Each project row carries a tiny
  visual: a test-history trend line, or a progress bar while it is working.
- **Main area: a 12-column grid of panels.**
  - Row 1, full width, **hero**: project and task title, attempt chip, "right now"
    line, the loop stepper (plan → change → test → review → finish). Its right half is
    reserved for "how far along" (filled by the time-estimate roadmap item).
  - Row 2: **step by step** (5 columns), **tests** (3: ring chart, per-check list,
    run history as a bar strip), **track record** (4: four headline numbers).
  - Row 3: **where the time went** (8: compact timeline lanes with an axis), **where
    the agent works** (4: treemap preview).
  - Below the first screen: Git section, plots, decisions, notes, full history. Panels
    there may be wider, and open in detail when tapped.
- Phone: one column, hero first, then needs-you items, then the panels in the same order.

## Colour

Dark theme is the default; light stays available through the theme switch.
One colour per phase, used identically everywhere (live steps, timeline, progress, map):

| Token | Dark | Light | Meaning |
|---|---|---|---|
| `--plan` | `#6F7F96` | `#8A97A8` | planning, reading, searching |
| `--change` | `#5B93E6` | `#2F62A8` | making a change |
| `--test` | `#F0A92E` | `#C98510` | testing; also "working" |
| `--review` | `#A07CF0` | `#7650B5` | independent review, reviewer steps |
| `--polish` | `#EC6E9B` | `#C04E78` | follow-up fixes |
| `--pass` | `#35C08E` | `#18825F` | passing, finished |
| `--fail` | `#F0614E` | `#C33B2C` | failing, stuck |
| `--bg` / `--panel` / `--panel2` | `#0C1320` / `#121C2C` / `#18243A` | `#E4E8EC` / `#F7F8F9` / `#EEF1F4` | surfaces |
| `--ink` / `--muted` / `--rule` | `#E6ECF4` / `#8796AB` / `#24324A` | `#111A26` / `#5E6B7B` / `#CBD3DC` | text and lines |

"Needs you" uses the accent (blue) for decisions and permission waits, red for stuck.

## Type

A condensed sans for headings, panel labels and large numbers (IBM Plex Sans Condensed),
a tight sans for body text (Inter Tight), a mono for times, durations and file names
(JetBrains Mono). Each with system fallbacks, since the page must work offline.

## Keep

Plain language, everything the README describes, accessibility (contrast in both
themes, keyboard focus, reduced motion), and no sideways scrolling on phones.
