---
name: imagegen
description: Generate or edit raster images with OpenAI's gpt-image models, on your ChatGPT plan through your Codex login (or a switch proxy, or OpenAI's Image API on request) — UI mockups and design concepts, website and game assets, illustrations, product shots, textures, sprites, transparent cutouts, and edits of existing images or screenshots. Use when the deliverable is a bitmap; not for icons, logos or diagrams that belong in SVG/HTML/CSS, and not for extending an existing vector asset set.
---

# Image generation

Claude Code has no built-in image tool. Every image goes through one command, which calls an
OpenAI Images API and writes files to disk:

```sh
"<base>/scripts/imagegen" generate --model gpt-image-2 --prompt-file /tmp/brief.txt \
  --size 1536x1024 --quality high --out /tmp/imagegen/<project>/<name>.png
```

`<base>` is the "Base directory for this skill" shown when this skill loads. The wrapper
supplies `openai` and `pillow` through `uv` and prints `imagegen: model <id> via <backend>`
before calling the API.

Backend (`IMAGEGEN_BACKEND`). Unset, it is `subscription` where a switch proxy is configured and
`codex` everywhere else; a failure never moves to another backend:

- `codex`: the ChatGPT plan, through this machine's own Codex login (`codex login` with a ChatGPT
  account). A loopback bridge, `scripts/codex_images.py`, answers the Images API calls with the
  image tool of the backend Codex itself uses. No OpenAI key and no proxy. It draws on the same
  usage limits as Codex, and it never refreshes Codex's login: an expired one is reported with
  what to do. The backend is not a documented OpenAI API and can change without notice.
- `subscription`: the ChatGPT plan, through a claude-switch proxy's Images API routes. The proxy
  address is `CLAUDE_SWITCH_PARENT_HTTPS_PROXY` (or `IMAGEGEN_PROXY_URL`) and the login comes from
  the machine's `proxyAuthHelper`.
- `api`: OpenAI's Image API on `OPENAI_API_KEY` (billed API credits). Only when the user asks.

On `codex` and `subscription` the ChatGPT image tool draws with its own model, gpt-image-2-codex.
`--model` must still name a gpt-image model, but it is not forwarded, and the wrapper reports the
model that actually drew. Native transparency works there: `--background transparent` is honoured.
The vendored script only lets it through with `--model gpt-image-1.5`, which on these backends
changes nothing else.

## Rules

- Pass `--model` explicitly and report the model the wrapper's `imagegen: model …` line names
  with every image. Default `gpt-image-2`. On `api`, never switch models (for example to
  `gpt-image-1.5` for native transparency) without asking.
- If the backend is unavailable (no Codex login or an expired one, no switch proxy, usage limit
  reached, no key for `api`), `uv` is missing, or the call fails: stop and report the error line.
  Do not switch backends, and do not substitute an SVG/HTML placeholder or a different provider,
  without asking.
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
- Report final paths, the final prompt, and the model.

## Generate or edit

- No input images, or images only as style/composition references → **generate**. References are
  passed to `edit --image` and described by index in the prompt ("Image 1: reference for layout").
- Change an existing image while preserving parts of it → **edit** (`--image` target, optional
  `--mask`). List invariants: "change only X; keep Y unchanged".
- Transparent output: `gpt-image-2` on the `api` backend does not support `background=transparent`.
  Generate on a flat chroma-key background, then
  `"<base>/scripts/imagegen" remove-chroma-key --input in.png --out out.png --auto-key border`.
  If that is not good enough: on `codex` or `subscription`, regenerate with
  `--model gpt-image-1.5 --background transparent --output-format png` (the same image model draws
  it); on `api`, ask before switching to `gpt-image-1.5`.

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

- `references/prompting.md` — prompting principles.
- `references/sample-prompts.md` — copy/paste recipes by asset type (website, game, UI, logo).
- `references/cli.md` — every subcommand and flag, batch JSONL format, downscaling.
- `references/image-api.md` — API parameters, sizes, quality, model constraints.

`gpt-image-2` sizes: `auto` or `WxH` with both edges multiples of 16, max edge 3840, ratio ≤ 3:1,
0.65–8.3 MP. Common: `1024x1024`, `1536x1024`, `1024x1536`, `2048x1152`, `3840x2160`.
