# Writing the concept brief

Guidance, not a template. Write a design-director brief in prose, tailored to
the task. Load `design:imagegen` for prompt mechanics and flags.

## Must be in the brief

Pull these from the request, screenshots, the existing app, or the agreed
plan. Do not collapse them into "modern landing page".

- Scope: whole page, app screen, dashboard, game screen, or a named set of
  section and state concepts. Name each section needing its own image.
- Purpose and audience: what it helps someone do, and who they are.
- Exact visible content: headlines, labels, CTAs, section names, nav items,
  table fields, sample entities, dates, prices, statuses, required copy.
  Once accepted this becomes the copy lock.
- Structure: first viewport, section order, sidebars, rails, drawers, tables,
  charts, media areas, forms, footer, responsive continuation.
- Interaction model: selected state, hover and focus, filters, tabs, mode
  switches, create and edit flow, success state, playback, HUD.
- Visual system: palette mood, type personality, content and chrome type
  scales, density, spacing rhythm, radii, shadows, borders, container model,
  card usage, icon style, image treatment, brand direction.
- Implementation constraints: UI text and controls stay code-native; product
  and background assets render fully with their own text and branding;
  separable assets; reusable component families; accessible and responsive.
  Name the repo's stack, or React + Vite if there is none.
- Negative constraints: no header-only crop for a full-surface ask, no extra
  product areas, no fake metrics, no decorative filler, no default card grids,
  no hero eyebrow/kicker/badge/pill unless requested or already in the
  reference, no clashing gradients, no pasted-looking images, no unrelated
  sections, no new claims, no app UI text baked into images.

## How many images

Readability beats compactness. A compressed full-page board is not a spec.

- One section, one concept. Two to ten sections, two to ten coordinated
  concepts — one fresh image per major section.
- A full-page overview is optional and only establishes rhythm and order.
- Add detail concepts whenever text, buttons, card anatomy, typography,
  spacing, or color are not clearly readable.
- Dashboards, editors, dense screens: the full primary screen plus focused
  concepts for sidebars, tables, inspectors, modals, charts, toolbars, forms,
  and selected states.
- Never crop, slice, or zoom an earlier image as the reference. Ask for a
  fresh standalone image in the same palette, type mood, component family,
  density, and asset treatment.
- Do not cut the image count if it turns implementation into guesswork.

## By surface

Full page or app: first viewport, section rhythm, workflow anatomy,
downstream states, responsive continuation. Marketing pages need a strong
hero and clear CTA before feature density; interactive hero chrome only for
software previews, not editorial, food, venue, or consumer heroes. App
screens need the real interaction model and must decompose into components.

Redesign from a screenshot: pass the screenshot as the edit reference.
Preserve navigation meaning, brand cues, content hierarchy, controls, and
page purpose. Improve spacing, type, hierarchy, color, image treatment, and
component polish. Invent nothing.

Hero or single section: only when the user asked for a page slice. Include
surrounding context so the page can continue consistently.

Long content pages: coordinated per-section concepts, one accepted layout
concept owning structure and order, every supporting concept sharing the
same brand language.

Games: play surface, HUD and control placement, art direction, reward and
hazard language, plus an asset pass for sprites, tiles, collectibles,
hazards, goals, props, and parallax layers. HUD text, score, physics, and
collision stay in code.

## Assets

- Real app UI text, fields, nav, and controls live in code.
- Product images, backgrounds, posters, packaging, signage, and brand scenes
  render completely, with the text and branding that belong to the asset.
  Quote exact asset text and require it verbatim when it matters.
- Make standalone versions of any logo, mark, label, package, poster, or
  branded object before coding, with transparent variants where they layer
  into code UI.
- SVG for icons; generated images for logos, marks, and non-icon art.
- Do not crop a page concept into production UI as a shortcut.
- Supporting assets must match the accepted concept, not start a new direction.

## After each generation

- Read the PNG. Reject it if it is header-only for a full-surface ask,
  cluttered, generic, repetitive, unreadable, over-decorated, or impractical.
- Extract per image: section purpose, visual priority, readable text, type
  relationships, spacing, control styling, container logic, colors, image
  treatment, and anything unclear.
- Still unclear? Generate a new standalone detail image. Do not crop.
