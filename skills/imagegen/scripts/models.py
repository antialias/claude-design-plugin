#!/usr/bin/env python3
"""`imagegen models`: the switch proxy's image classes, read from its /v1/models.

Each class is a list of providers (members) the proxy walks in order for a picture. The proxy says,
per class and per member, who can draw now and what each accepts; this prints one compact block per
class:

    images (default): <who can draw now>
      accepts: <what the class accepts>
      - gpt/gpt-image-2 [no]: <why>
        accepts: <what this member accepts>
      - runway/gpt_image_2 [paid]: <why>
        accepts: <...>

A member's check is `included` (the plan's own allowance), `paid` (credits or a balance) or `no`.
Only these fields are printed; others are ignored and a missing one is left out.

    models.py <proxy base URL ending in /v1>
      IMAGEGEN_PROXY_LOGIN  the proxy login (base64 name:secret), sent as a Bearer
      IMAGEGEN_CLASS        optional: print only this class
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def accepts(row) -> str:
    return text(row.get("accepts", {}).get("summary")) if isinstance(row.get("accepts"), dict) else ""


def render(rows) -> list[str]:
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        head = text(row.get("id")) or "(unnamed class)"
        if row.get("default") is True:
            head += " (default)"
        summary = text(row.get("summary"))
        lines.append(f"{head}: {summary}" if summary else head)
        if accepts(row):
            lines.append(f"  accepts: {accepts(row)}")
        members = row.get("members")
        for member in members if isinstance(members, list) else []:
            if not isinstance(member, dict):
                continue
            line = "  - " + (text(member.get("id")) or "(unnamed member)")
            if text(member.get("check")):
                line += f" [{text(member.get('check'))}]"
            if text(member.get("summary")):
                line += f": {text(member.get('summary'))}"
            lines.append(line)
            if accepts(member):
                lines.append(f"    accepts: {accepts(member)}")
        lines.append("")
    return lines[:-1] if lines else lines


def refusal(body: bytes) -> str:
    try:
        message = json.loads(body)["error"]["message"]
        if isinstance(message, str) and message:
            return message
    except (ValueError, KeyError, TypeError):
        pass
    return " ".join(body.decode("utf-8", "replace").split())[:300]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: models.py <proxy base URL ending in /v1>", file=sys.stderr)
        return 2
    url = argv[1].rstrip("/") + "/models"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ.get('IMAGEGEN_PROXY_LOGIN', '')}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as e:
        said = refusal(e.read())
        if e.code == 404:
            print(f"imagegen: {url} answered 404 ({said}); this proxy has no image model list", file=sys.stderr)
        else:
            print(f"imagegen: {url} answered {e.code}: {said}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"imagegen: could not reach {url}: {getattr(e, 'reason', e)}", file=sys.stderr)
        return 1
    try:
        rows = json.loads(body).get("data")
    except (ValueError, AttributeError):
        rows = None
    if not isinstance(rows, list):
        print(f"imagegen: {url} did not answer with a model list", file=sys.stderr)
        return 1
    wanted = os.environ.get("IMAGEGEN_CLASS", "")
    if wanted:
        rows = [row for row in rows if isinstance(row, dict) and row.get("id") == wanted]
        if not rows:
            print(f"imagegen: the proxy lists no class {wanted}; run `imagegen models` for the ones it has", file=sys.stderr)
            return 1
    lines = render(rows)
    print("\n".join(lines) if lines else "The proxy lists no image classes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
