---
name: imagegen
description: Generate or edit raster images through the switch proxy's image endpoint, by image class — UI mockups and design concepts, website and game assets, illustrations, product shots, textures, sprites, transparent cutouts, and edits of existing images or screenshots. Use when the deliverable is a bitmap; not for icons, logos or diagrams that belong in SVG/HTML/CSS, and not for extending an existing vector asset set.
---

# Image generation

Claude Code has no built-in image tool. Every image goes through one command, which calls an
Images API and writes files to disk:

```sh
"<base>/scripts/imagegen" generate --prompt-file /tmp/brief.txt \
  --size 1536x1024 --quality high --out /tmp/imagegen/<project>/<name>.png
```

Through a switch proxy, add `--class <name>` to choose the image class (below). On `codex` and
`api`, `--class` is an error.

`<base>` is the "Base directory for this skill" shown when this skill loads. The wrapper
supplies `openai` and `pillow` through `uv` and, before calling the API, prints the backend it
calls: `imagegen: model <id> via <backend>`, or on `subscription`
`imagegen: via switch proxy <url>`.

Backend (`IMAGEGEN_BACKEND`). Unset, it is `subscription` where a switch proxy is configured and
`codex` everywhere else; a failure never moves to another backend:

- `codex`: the ChatGPT plan, through this machine's own Codex login (`codex login` with a ChatGPT
  account). A loopback bridge, `scripts/codex_images.py`, answers the Images API calls with the
  image tool of the backend Codex itself uses. No OpenAI key and no proxy. It draws on the same
  usage limits as Codex, and it never refreshes Codex's login: an expired one is reported with
  what to do. The backend is not a documented OpenAI API and can change without notice.
- `subscription`: the switch proxy's image endpoint. You name an image class (below) and the
  proxy decides who draws it. The proxy address is `CLAUDE_SWITCH_PARENT_HTTPS_PROXY` (or
  `IMAGEGEN_PROXY_URL`) and the login comes from the machine's `proxyAuthHelper`.
- `api`: OpenAI's Image API on `OPENAI_API_KEY` (billed API credits). Only when the user asks.

Nobody passes `--model` on `codex` or `subscription`; the wrapper refuses it. On `subscription`
your one choice is the image class; the proxy decides the rest. `--background transparent` is
honoured on `codex` and passed through on `subscription`.

`--model` is an `api` matter only. There the default is `gpt-image-2`, and switching models needs
asking.

## Image classes (switch proxy)

On `subscription` every picture comes from an image class. Pick one with `--class <name>` or
`IMAGEGEN_CLASS`; unset, it is `images`, which suits nearly everything.

`"<base>/scripts/imagegen" models` lists the classes, whether each can draw now and what each
accepts. Run it before an unusual size, a mask or big reference images, and pick a class that can
draw that. Classes exist only under the switch proxy; on `codex` or `api`, `--class` is an error.

Sizes every class draws:

<!-- sizes:begin -->
- auto
- 1024x1024
- 1536x1024
- 1024x1536
- 2048x1152
- 1152x2048
<!-- sizes:end -->

Any other size may narrow which classes can draw; `imagegen models` lists what each accepts.

## Rules

- Do not pass `--model` on `codex` or `subscription`; through a switch proxy, choose a class with
  `--class` instead. On `api`, leave the default `gpt-image-2` and never switch models (for
  example to `gpt-image-1.5` for native transparency) without asking.
- With every image, report the image class it came from (on `codex` or `api`, the model its
  `imagegen: model …` line names). Who draws a class's pictures is the proxy's business: don't
  report, compare or ask about providers, plans, credits or costs.
- If the backend is unavailable (no Codex login or an expired one, the plan's usage limit on
  `codex`, no switch proxy, no key for `api`) or `uv` is missing: stop and report the error line.
- When the switch proxy refuses a picture:
  - A 400 names the field (`param`) and the values that would draw, such as the nearest sizes:
    change that one thing and run again.
  - Otherwise (a 429), report the reply's own words, then check `imagegen models`. If another
    class can draw now, retry in it, or ask the user. Never conclude that images are unavailable
    while `imagegen models` shows a class that can draw.
- Do not switch backends, and do not substitute an SVG/HTML placeholder, without asking. Switching
  to the billed API (`IMAGEGEN_BACKEND=api`) needs the owner's word each time, whatever the
  proxy said.
- Never edit `scripts/image_gen.py` or `scripts/remove_chroma_key.py`; they are vendored
  verbatim from OpenAI's Codex imagegen skill (Apache-2.0, `LICENSE.txt`). Missing capability →
  ask the user.
- Use `--dry-run` to check a payload without spending a call.
- Do not overwrite an existing asset unless asked; write a sibling (`hero-v2.png`).
- Cost: `--quality high` for concepts and finals; `low` only for drafts the user asked to be
  quick or cheap. `--n` is for variants of one prompt; distinct assets get distinct prompts
  (`generate-batch` with a JSONL file for many).

## Look at every result

Read each output PNG with the Read tool before describing or using it — you can see images you
Read. Check subject, composition, text accuracy (spelling, verbatim copy), and the
constraints/avoid list. Iterate with one targeted change at a time, repeating invariants.

Show the user: `open <png>` on macOS, and send it with SendUserFile when that tool is available
(they may be following from another device). The terminal cannot render images inline.

## Where files go

- Previews and drafts: `/tmp/imagegen/<project>/`.
- Assets the project uses: copy the chosen file into the workspace (repo convention, else next
  to the consuming code) and update references. Never leave a project asset only in `/tmp`.
- Report final paths, the final prompt, and the class each image came from (see Rules).

## Generate or edit

- No input images, or images only as style/composition references → **generate**. References are
  passed to `edit --image` and described by index in the prompt ("Image 1: reference for layout").
- Change an existing image while preserving parts of it → **edit** (`--image` target, optional
  `--mask`). List invariants: "change only X; keep Y unchanged".
- Transparent output: `gpt-image-2` on the `api` backend does not support `background=transparent`.
  Generate on a flat chroma-key background, then
  `"<base>/scripts/imagegen" remove-chroma-key --input in.png --out out.png --auto-key border`.
  If that is not good enough: on `codex` or `subscription`, regenerate with
  `--background transparent --output-format png`. Sizes are then 1024x1024, 1536x1024, 1024x1536
  or auto. In a batch, put it on the command line, not in a job. On `api`, ask before switching to
  `gpt-image-1.5`.

## Prompt shape

Structure the prompt as a labelled spec; use only the lines that help:

```text
Use case: <ui-mockup | product-mockup | illustration-story | stylized-concept | ...>
Asset type: <where it will be used>
Primary request: <the user's request>
Input images: <Image 1: role; Image 2: role>
Scene/backdrop / Subject / Style/medium / Composition/framing / Lighting/mood / Color palette
Text (verbatim): "<exact text>"
Constraints: <must keep / must avoid>
```

If the user's prompt is specific, normalize it without adding creative requirements. If it is
generic, add only detail that materially helps (framing, polish level, intended use). Do not add
characters, brands, slogans or palettes the request does not imply. Quote exact text; spell
tricky words letter by letter.

## References

Vendored from the Codex skill. They describe Codex's built-in `image_gen` tool as the default and
the CLI as a fallback; here the CLI is the only path, so read "built-in" guidance as "the CLI",
and run `"<base>/scripts/imagegen"` wherever they say `python "$IMAGE_GEN"` or a `$CODEX_HOME` path.
Their `--model` flags apply only on `api`; on `codex` and `subscription`, leave them out.

- `references/prompting.md` — prompting principles.
- `references/sample-prompts.md` — copy/paste recipes by asset type (website, game, UI, logo).
- `references/cli.md` — every subcommand and flag, batch JSONL format, downscaling.
- `references/image-api.md` — API parameters, sizes, quality, model constraints.

Sizes on `codex` and `api`: `auto` or `WxH` with both edges multiples of 16 and at most 3840,
ratio ≤ 3:1, 0.65–8.3 MP. On the switch proxy, keep to the sizes every class draws (Image
classes, above) unless `imagegen models` says your class takes another.
