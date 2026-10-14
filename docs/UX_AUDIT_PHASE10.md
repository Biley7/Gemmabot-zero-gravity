# Phase 10 — Final product-design audit (2026-10-14)

Scope: visual-language and interaction review only. No new functionality, no
backend changes. Verdict up front: GemmaBot already reads as a control console
— dark graphite instrument palette, monospace telemetry, one status vocabulary,
SVG simulator, state carried by 2px edges instead of banners. This pass closes
the remaining gaps between "coherent project" and "product".

## Audit by criterion

| # | Criterion | Finding | Action |
|---|---|---|---|
| 1 | Visual hierarchy | Strong: zone bars → instrument → muted footer everywhere; the guard verdict is the loudest element per panel | kept |
| 2 | Typography | Two stacks, 5-step scale, honest: one mono telemetry, one sans prose | kept |
| 3 | Spacing | 4px grid derived from one token module; no magic numbers outside `spacing.py` | kept |
| 4 | Alignment | Baseline-aligned head bars, grid rows, telemetry | kept |
| 5 | Component consistency | Blocks/panels shared; labs cannot drift (`gb-*` classes declared once) | kept |
| 6 | Button hierarchy | Primary accent vs bordered default vs disabled (declared last, wins) | kept |
| 7 | State communication | Six-word status vocabulary derived from real events; chip + sentence + mono meta | **improved: announced** |
| 8 | Error communication | Refusal names the exact check, action, cell — from the verifier's records, never from model prose | kept |
| 9 | Loading states | Spinner is mono, muted, says what is waited on | kept |
| 10 | Empty states | One dashed-empty grammar, dense variant for the sidebar | kept |
| 11 | Responsive | Board/tabs scroll instead of squeezing; 1100px and 720px breakpoints | kept |
| 12 | Accessibility | `:focus-visible` rings existed; muted text failed WCAG AA (3.15:1) | **improved** |
| 13 | Keyboard interaction | Native tabs/details/buttons + visible focus + documented shortcuts | **improved: board label** |
| 14 | Animation timing | Token-durations only (80–500ms), easing curves named; nothing bounces | kept; silenced under reduced motion |
| 15 | Information density | Console-density, not dashboard-density; facts share a compact grid | kept |
| 16 | Visual noise | No shadow noise, no gradients; glows only on the robot (function) | **removed mascot + duplicates** |
| 17 | Colour contrast | Muted label greys sat below AA on panel surfaces | **fixed (≥4.5:1)** |
| 18 | Simulator prominence | Viewport is the hero column, instrument frame, SVG, legend | **improved: accessible board** |

## Changes made

**Files changed**
- `frontend/components/colors.py` — `TEXT_MUTED`, `GRID_LABEL`,
  `TELEMETRY_LABEL` lifted `#5c6270` → `#7e8593`. The smallest labels
  (coordinates, telemetry keys, placeholders-adjacent captions) now hold
  ≥4.5:1 against every panel surface they sit on (previously 3.15:1).
  Hierarchy survives: secondary (`#9299a8`) remains measurably lighter.
- `frontend/console/shell.py` — the console status bar is now a live region
  (`role='status' aria-live='polite'`), so the run's state change reaches a
  screen reader instead of only repainting.
- `frontend/simulation/ui_helpers.py` — the simulator board is one labelled
  image (`role='img'` + an aria-label saying the grid size, robot cell and
  heading, goal cell, obstacle count) instead of 64 anonymous SVG cells;
  no emoji glyph exists in the hero grid output.
- `app.py` — removed the duplicated `BENCHMARK_REPORT_MD` definition; tab icon
  is the `precision_manufacturing` material mark instead of the 🤖 mascot.
- `tests/test_design_pass.py` (new) — computes WCAG contrast with WCAG 2.x
  maths rather than asserting hexes by eye (information greys ≥4.5:1 on every
  surface; body text ≥7:1; state colours ≥4.5:1 on their state backgrounds),
  and pins the live region, the reduced-motion block, the labelled board, and
  the no-emoji / one-definition rules.

**Components changed** — `gb-console-bar` (announced state), `gb-hero-grid`
(labelled board), the three grey tokens (all surfaces), the page icon.

**Accessibility improvements** — AA contrast for muted labels on every panel
surface; the console status and the simulator world are perceivable without
sight; `prefers-reduced-motion` silences every animation and the player
respects it before autoplaying (existing behaviour, now pinned by test).

**Deliberately not changed** — gradients (there are none), glows on the robot
cell and refused cell (they encode state), panel borders (they are the density
system), the shared blocks (removing them would reduce clarity, not noise).

## The 10-second question
1. *What does it do?* Wordmark + "AI Robotics Validation Platform", and the
   guard panel's own first line: "Validate AI-generated robot plans before
   execution."
2. *Where is the AI?* Header names the configured backend and model; the MODEL
   row is the quietest thing in the Guard panel.
3. *Where does verification happen?* The Guard panel — verdict banner, seven
   stages, four checks, each a named, dated mechanic.
4. *May the robot execute?* The verdict is the first, largest structured
   element on every run; execution without a sealed approval is impossible in
   the runtime.
5. *What happened last time?* The console status bar (announced live) states
   the verdict and whether the approved plan actually stepped.

## Tests
Full suite after the pass: **785 passed** — the Phase-9 suite (770) plus the 15
design-pass pins in `tests/test_design_pass.py`, all green.

## Remaining UX risks
- The execution player runs in an iframe; focus is currently delegated to its
  buttons, but a full keyboard-review of iframe focus (Tab into/out, Escape)
  is still manual and browser-dependent.
- `TEXT_MUTED` on `BG_OVERLAY` (input hover backgrounds) is ~4.2:1; inputs
  themselves are primary-coloured text, so only their hover tint is affected.
- Streamlit-native widgets (date pickers, select menus) render some styling
  the design system cannot reach without upstream hooks.
- Streamlit's own spinner keeps its animated glyph; it is styled but not
  replaceable without forking the component.
