---
name: ui-concept
description: Design a UI with generated image concepts before writing code, then implement the accepted concept faithfully. Use when asked to design a screen or page, redesign/restyle/modernize an existing UI, make something look better, produce a mockup or concept, or build a new frontend app, dashboard, landing page, hero section, or game screen. Not for small fixes inside an established design system.
---

# UI Concept

Design first, then build. Act as a senior product designer until a concept is
accepted, then as an engineer implementing an approved spec.

Two rules outrank the rest:

1. Produce a good, complete, readable image concept before any UI code.
2. Do not stop until the built UI matches the accepted concept. Keep fixing
   drift in layout, copy, type, color, assets, and responsive behavior.

## When to use

- New frontend surfaces: apps, dashboards, tools, landing pages, games.
- A redesign, restyle, or modernization of something that exists.
- Any explicit "design it first" / "show me a mockup" request.

Skip it for a small change inside an existing design system (spacing fix,
one table row, copy tweak). Say you are skipping it and why.

## Image generation

Load the sibling `design:imagegen` skill for prompt craft and flags. The
wrapper is at:

```
<skill base dir>/../imagegen/scripts/imagegen generate|edit|generate-batch ...
```

Claude Code prints "Base directory for this skill: <dir>" on load; resolve
the path from that.

- `--quality high`, `--size 1536x1024` landscape or `1024x1536`
  mobile/portrait. `--quality low` only when the user asks for speed or cost.
- Drafts to `/tmp/imagegen/<project>/`. Copy the accepted concept into the
  repo (its own convention, else `docs/design/`) — it is the spec.
- Report the model used for every image.
- Redesign: screenshot the current app and pass it as `edit --image <png>`,
  which preserves the real information architecture.

No silent fallbacks. If imagegen's backend is unavailable or generation fails,
stop and say so. Never hand-write an HTML or SVG mockup in place of the
concept without asking.

## Brief writing

Full guidance in `references/briefing.md`. The short version:

- Copy the concrete requirements in: purpose, audience, required sections and
  states, supplied copy, nav and CTA labels, data fields, media, responsive
  needs, stack constraints.
- Preserve the source material's information architecture. The model must not
  invent sections, nav, metrics, claims, or product areas.
- Ask for the complete surface, not just a hero. One image per major section
  or state; 1-10 sections means roughly 1-10 images.
- If a detail is too small or ambiguous to implement, generate a fresh
  standalone detail image in the same system. Never crop an earlier image
  and call it the spec.

## Review, show, approve

Read every generated PNG with the Read tool before showing it — you can see
images you Read. Judge them yourself first. Reject and regenerate a concept
that is header-only for a full-surface ask, cluttered, generic, repetitive,
unreadable, over-decorated, carries invented sections or fake metrics, or is
impractical to implement.

Show the user with `open <png>` on macOS, plus SendUserFile when available —
they may be following from another device. The terminal cannot render inline.

Get approval before writing code: AskUserQuestion with approve as spec /
iterate with notes / different direction, or plain conversation. Do not
implement while the user is still reviewing.

Once accepted, the concept is a production spec. No creative liberties: do
not reinterpret layout, copy, hierarchy, containers, density, color, or
section order. Design taste does not override the concept.

## Quality bar and visual defaults

Aim for a professional product mockup: one clear creative idea, a strong
first viewport with a clear offer and primary action, deliberate whitespace,
and a coherent system of palette, spacing, radii, borders, shadows, icons,
and component geometry. Typography carries the hierarchy, control and chrome
text included — never browser defaults. Defaults absent art direction:

- Roughly 7/10 creativity: distinctive but buildable. "Clean" means edited
  and legible, not empty. Low-to-medium density, generous spacing.
- Quiet header: brand mark, essential nav, one primary action.
- One or two strong image moments beat many small decorations.
- Open layouts, bands, rails, lists, tables, canvases over nested cards,
  bento grids, and over-framed dashboards.
- Vary rhythm across a long page's sections while keeping one brand system.
- Media in stable frames with consistent crop and radius.
- No hero eyebrow, kicker, badge, or pill above the main heading unless
  requested or already in the reference. No fake metrics or filler cards.

## Before coding

Inventory the accepted concept. Write it down; implement from it.

- Copy lock: every visible string — nav, headings, CTAs, labels, proof
  points, data labels. Nothing outside the list ships.
- Tokens: background, surface, text, muted text, border, shadow, accent,
  semantic colors, radii, elevation, spacing scale, motion timing.
- Color lock: name each background as true white, off-white, cream, gray,
  dark, or tinted, and implement exactly that. No tasteful warming.
- Type system: family and fallback, scale, weights, line heights, tracking,
  label and control styles, responsive behavior.
- Icon inventory: every icon, glyph, and chevron — meaning, outline vs
  filled, stroke width, size, color, alignment, spacing, states.
- Container rules: which of cards, panels, rails, bands, lists, tables,
  canvases, drawers, modals, full-bleed the concept uses, and which component
  families are allowed. Anything not shown is prohibited unless asked for.
- Media treatment per image: overlay / gradient / edge fade / mask /
  transparent / matching background. No overlay in the concept, none in code.
- Component plan: app shell, nav, feature regions, reusable primitives, data
  and state helpers. Not one giant `App`.

Use the imagegen skill to make standalone assets for any logo, mark, product
render, packaging, poster, or branded object in the concept, with transparent
backgrounds where they layer into code UI.

## Implementation

- Follow the repo's framework, routing, styling, state, and asset
  conventions. New complex app with no constraint: React + Vite.
- Build the real usable surface, not a marketing shell around a future app.
- Keep interactive UI text and controls code-native. Text belonging to a
  product image, poster, sign, or photo stays in the raster asset. Never
  ship a screenshot as UI.
- SVG for icons and directional glyphs, matched to the icon inventory. Do not
  swap filled for outline or a specific metaphor for a generic one.
- Multi-section pages: build one section, screenshot it, compare it to that
  section's concept, fix drift, then move on.
- Bridge sections with spacing, bands, alignment, and type rhythm — not new
  carousels, accordions, tab systems, or pricing blocks.
- Motion only where it clarifies; respect `prefers-reduced-motion`.
- Run the repo's type, lint, and test checks.

## Verification

1. Drive a real browser: Claude in Chrome tools via the `claude-in-chrome`
   skill, or the chrome-devtools MCP. Playwright only when neither works —
   say so and why.
2. Screenshot at desktop and mobile widths, at the concept's native
   dimensions when practical; otherwise record the blocker.
3. Click through the core workflow. Controls must change real local state.
4. Read both the accepted concept PNG and the latest screenshot in the same
   pass and compare them directly. Mandatory; browsing the page and passing
   tests do not substitute.
5. Check at least five concrete points across copy, layout, typography,
   palette and gradients, asset treatment, container model, spacing,
   responsive behavior, and motion. Diff visible copy against the copy lock.
6. Per mismatch, record what differs, concept evidence, render evidence, and
   the fix or the reason not fixed. Keep fixing until nothing fixable remains.

Hard stops: clipped content, accidental wrapping, placeholder boxes,
invented copy, mismatched colors, white turned to cream, unapproved overlays,
substituted or generic icons, images that do not blend, unreadable text,
type-scale drift, default control typography, mobile overflow.

Delete temporary QA screenshots and scratch files before handoff.

## Final report

State the accepted concept's path, the model used per image, the browser tool
used or the fallback reason, that you Read both the concept and the final
screenshot, the viewports checked, the comparison points inspected, the
copy-lock diff result, mismatches fixed, remaining intentional deviations,
and the core interaction path verified. If nothing material remains, say so.
