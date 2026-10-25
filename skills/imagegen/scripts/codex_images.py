#!/usr/bin/env python3
"""The codex backend: OpenAI's Images API, served on loopback from this machine's own Codex login.

A ChatGPT plan already pays for image generation through the `image_generation` tool of the
backend Codex talks to (chatgpt.com/backend-api/codex/responses). This bridge accepts the two
Images API calls the vendored image_gen.py makes, POST /v1/images/generations (JSON) and
POST /v1/images/edits (multipart), and answers each with one Responses call that carries the
prompt, any input images and the tool's options. It is a port of the switch proxy's Images
routes, so the request shape is the one that proxy proved live.

    codex_images.py check                    validate the login and print the host model
    codex_images.py serve --port-file FILE   listen on 127.0.0.1, write the port to FILE

What it deliberately does not do:

- Refresh the login. It reads Codex's own login file (CODEX_HOME/auth.json) on every call and
  never writes it: refreshing here would rotate the refresh token out from under Codex. An
  expired or refused login is reported with what to do, and the call fails.
- Fall back. A refusal (quota, login, upstream error) is answered as an error carrying
  `x-should-retry: false`, so the OpenAI SDK neither retries it nor reaches for anything else.
- Forward `model`. The tool draws with its own image model (gpt-image-2-codex when the switch
  proxy probed it); a gpt-image-* name is accepted and otherwise ignored, anything else refused.

Only the standard library is used, so any python3 runs it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

UPSTREAM = os.environ.get("IMAGEGEN_CODEX_BASE_URL", "https://chatgpt.com").rstrip("/")
RESPONSES_PATH = "/backend-api/codex/responses"
# The header trio the backend requires; the same values the switch proxy's codex lane sends.
ORIGINATOR = "codex-cli"
USER_AGENT = "codex-cli/0.137.0"
INSTRUCTIONS = "You make images with the image_generation tool. Call it once with the user's prompt; add no commentary."
CALL_TIMEOUT = 240  # one socket read of one call; high quality can take minutes
# The whole request, every image of an n>1 batch included. It must end before the OpenAI SDK's own
# 600 s read timeout: a request the SDK abandons is one it retries, spending the batch again.
DEADLINE = float(os.environ.get("IMAGEGEN_CODEX_DEADLINE") or 540)
MAX_N = 10
CONCURRENCY = 3
JSON_CAP = 1 << 20
EDIT_CAP = 128 << 20

QUALITIES = {"low", "medium", "high", "auto"}
BACKGROUNDS = {"transparent", "opaque", "auto"}
FORMATS = {"png", "jpeg", "webp"}
MODERATION = {"auto", "low"}
SIZE_RE = re.compile(r"^[1-9][0-9]*x[1-9][0-9]*$")

RERUN = "use Codex once (any prompt) so it refreshes its login, or run `codex login`; then try again"


class Refusal(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


# ---- the login ----


def jwt_exp(token: str):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except (IndexError, ValueError, AttributeError):
        return None


def load_login():
    path = codex_home() / "auth.json"
    if not path.is_file():
        raise Refusal(
            401,
            "no_codex_login",
            f"no Codex login at {path}: run `codex login` and sign in with ChatGPT. This backend reads "
            'Codex\'s login file; if Codex keeps its login in the OS keyring, set cli_auth_credentials_store = "file" '
            "in config.toml and log in again",
        )
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Refusal(401, "unreadable_codex_login", f"cannot read {path}: {e}") from None
    tokens = data.get("tokens") or {}
    token, account = tokens.get("access_token"), tokens.get("account_id")
    if not token or not account:
        if data.get("OPENAI_API_KEY"):
            raise Refusal(
                401,
                "codex_api_key_login",
                "Codex is signed in with an API key, not a ChatGPT account; run `codex login` and choose "
                "ChatGPT, or use IMAGEGEN_BACKEND=api",
            )
        raise Refusal(401, "no_codex_login", f"{path} holds no ChatGPT login; run `codex login`")
    exp = jwt_exp(token)
    if isinstance(exp, (int, float)) and exp <= time.time() + 60:
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(exp))
        raise Refusal(401, "codex_login_expired", f"the Codex login expired at {when}; {RERUN}")
    return token, account


def host_model() -> str:
    """The Responses model that hosts the image tool: the one this machine's Codex uses."""
    if os.environ.get("IMAGEGEN_CODEX_MODEL"):
        return os.environ["IMAGEGEN_CODEX_MODEL"]
    config = codex_home() / "config.toml"
    if config.is_file():
        for line in config.read_text().splitlines():
            if line.lstrip().startswith("["):
                break  # top-level keys only
            m = re.match(r'\s*model\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    cache = codex_home() / "models_cache.json"
    if cache.is_file():
        try:
            models = json.loads(cache.read_text()).get("models", [])
            listed = [m for m in models if m.get("visibility") == "list" and m.get("slug")]
            if listed:
                return min(listed, key=lambda m: m.get("priority", 1e9))["slug"]
        except (OSError, ValueError, AttributeError):
            pass
    raise Refusal(
        500,
        "no_host_model",
        f"no model in {config} and no model list in {cache}; set IMAGEGEN_CODEX_MODEL to a model Codex offers you",
    )


# ---- one request, normalised ----


def sniff(data: bytes):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def data_url(data: bytes) -> str:
    mime = sniff(data)
    if not mime:
        raise Refusal(400, "invalid_image", "an uploaded file is not png, jpeg or webp")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def normalise(fields: dict, images: list, mask) -> dict:
    model = fields.get("model") or ""
    if model and not model.startswith("gpt-image"):
        raise Refusal(404, "model_not_found", f"model {model!r} is not served by the Codex backend; it draws gpt-image only")
    if fields.get("response_format") not in (None, "", "b64_json"):
        raise Refusal(400, "invalid_response_format", "only response_format b64_json is served")
    if str(fields.get("stream", "")).lower() == "true" or fields.get("partial_images") not in (None, "", 0, "0"):
        raise Refusal(400, "unsupported_stream", "streaming and partial images are not served")
    if fields.get("input_fidelity"):
        raise Refusal(400, "invalid_input_fidelity_model", "input_fidelity is not supported: the ChatGPT image tool refuses it")
    prompt = (fields.get("prompt") or "").strip()
    if not prompt:
        raise Refusal(400, "missing_prompt", "prompt is required and must not be empty")
    try:
        n = int(fields.get("n") or 1)
    except ValueError:
        raise Refusal(400, "invalid_n", "n must be a number") from None
    if not 1 <= n <= MAX_N:
        raise Refusal(400, "invalid_n", f"n must be between 1 and {MAX_N}")
    tool = {"type": "image_generation"}
    size = fields.get("size")
    if size:
        if size != "auto" and not SIZE_RE.match(size):
            raise Refusal(400, "invalid_size", "size must be auto or WIDTHxHEIGHT, for example 1024x1024")
        tool["size"] = size
    for key, allowed in (
        ("quality", QUALITIES),
        ("background", BACKGROUNDS),
        ("output_format", FORMATS),
        ("moderation", MODERATION),
    ):
        value = fields.get(key)
        if value:
            if value not in allowed:
                raise Refusal(400, f"invalid_{key}", f"{key} must be one of {', '.join(sorted(allowed))}")
            tool[key] = value
    if tool.get("background") == "transparent" and tool.get("output_format") == "jpeg":
        raise Refusal(400, "invalid_background", "a transparent background needs output_format png or webp")
    if fields.get("output_compression") not in (None, ""):
        try:
            compression = int(fields["output_compression"])
        except ValueError:
            raise Refusal(400, "invalid_output_compression", "output_compression must be a number") from None
        if not 0 <= compression <= 100:
            raise Refusal(400, "invalid_output_compression", "output_compression must be between 0 and 100")
        tool["output_compression"] = compression
    if mask is not None:
        tool["input_image_mask"] = {"image_url": data_url(mask)}
    content = [{"type": "input_text", "text": prompt}]
    content += [{"type": "input_image", "image_url": data_url(img)} for img in images]
    body = {
        "model": host_model(),
        "instructions": INSTRUCTIONS,
        "input": [{"type": "message", "role": "user", "content": content}],
        "tools": [tool],
        "tool_choice": "auto",
        "stream": True,
        "store": False,
    }
    return {"n": n, "body": json.dumps(body).encode()}


def parse_multipart(content_type: str, raw: bytes):
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + raw)
    if not msg.is_multipart():
        raise Refusal(400, "invalid_multipart", "an edit must be multipart/form-data")
    fields, images, mask = {}, [], None
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True) or b""
        if name in ("image", "image[]"):
            images.append(data)
        elif name == "mask":
            if mask is not None:
                raise Refusal(400, "invalid_mask", "an edit takes one mask")
            if sniff(data) != "image/png":
                raise Refusal(400, "invalid_mask", "the mask must be a PNG")
            mask = data
        elif name:
            fields[name] = data.decode("utf-8", "replace").strip()
    if not images:
        raise Refusal(400, "missing_image", "an edit needs at least one `image` file part")
    return fields, images, mask


# ---- one upstream call ----


def stream_events(resp):
    """Yield each SSE data payload. readline, not a fixed buffer: one line carries a whole image."""
    while True:
        line = resp.readline()
        if not line:
            return
        line = line.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                yield payload


def aggregate(resp) -> dict:
    item, text, status, failure, finished = None, "", "", "", False
    for payload in stream_events(resp):
        try:
            ev = json.loads(payload)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "response.output_item.done":
            it = ev.get("item") or {}
            if it.get("type") == "image_generation_call":
                if it.get("status") == "completed" and it.get("result") and item is None:
                    item = it
            elif it.get("type") == "message":
                text = " ".join(t for t in [text] + [c.get("text", "") for c in it.get("content") or []] if t).strip()
        elif kind in ("response.completed", "response.incomplete", "response.failed"):
            finished = True
            r = ev.get("response") or {}
            status = r.get("status") or status
            if (r.get("error") or {}).get("message"):
                failure = r["error"]["message"]
            elif (r.get("incomplete_details") or {}).get("reason"):
                failure = "incomplete: " + r["incomplete_details"]["reason"]
    if item:
        return item
    if not finished:
        raise Refusal(502, "upstream_stream_broken", "the image backend's stream ended early, before the response finished")
    if failure:
        reason = failure
    elif text:
        reason = "the model answered with text instead of calling the image tool: " + text[:240]
    elif status and status != "completed":
        reason = "the upstream response ended " + status
    else:
        reason = "the upstream stream carried no image_generation_call item"
    raise Refusal(502, "no_image", "the image backend returned no image: " + reason)


def upstream_error(status: int, raw: str) -> Refusal:
    detail = raw.strip()[:300]
    if "usage_limit_reached" in raw:
        return Refusal(429, "usage_limit_reached", "the ChatGPT plan's usage limit is reached: " + detail)
    if status == 429:
        return Refusal(429, "rate_limit_exceeded", "the image backend asked us to slow down: " + detail)
    if status in (401, 403):
        return Refusal(401, "codex_login_refused", f"chatgpt.com refused the Codex login ({status}); {RERUN}")
    return Refusal(502, "upstream_error", f"the image backend answered {status}: {detail}")


def call_once(body: bytes) -> dict:
    token, account = load_login()  # read fresh each call: Codex may have refreshed it meanwhile
    req = urllib.request.Request(
        UPSTREAM + RESPONSES_PATH,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "ChatGPT-Account-Id": account,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "originator": ORIGINATOR,
            "User-Agent": USER_AGENT,
            "session_id": hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()[:32],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
            return aggregate(resp)
    except urllib.error.HTTPError as e:
        raise upstream_error(e.code, e.read(16 << 10).decode("utf-8", "replace")) from None
    except http.client.HTTPException as e:
        raise Refusal(502, "upstream_stream_broken", f"the image backend's stream ended early: {e!r}"[:300]) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Refusal(502, "upstream_unreachable", f"the image backend could not be reached: {e}") from None


def generate(request: dict) -> dict:
    pool = ThreadPoolExecutor(max_workers=min(request["n"], CONCURRENCY))
    futures = [pool.submit(call_once, request["body"]) for _ in range(request["n"])]
    try:
        done, pending = wait(futures, timeout=DEADLINE, return_when="FIRST_EXCEPTION")
        failed = [f for f in done if f.exception() is not None]
        if failed:
            raise failed[0].exception()
        if pending:
            # Worded without "timeout": the vendored batch command retries any error that says so.
            raise Refusal(
                504,
                "deadline_exceeded",
                f"the request ran past the bridge's {int(DEADLINE)} s limit before every image was drawn; ask for fewer per call",
            )
        items = [f.result() for f in futures]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # calls not yet started are never made
    first = items[0]
    out = {
        "created": int(time.time()),
        "data": [
            {"b64_json": it["result"], **({"revised_prompt": it["revised_prompt"]} if it.get("revised_prompt") else {})}
            for it in items
        ],
    }
    for key in ("background", "output_format", "quality", "size"):
        if first.get(key):
            out[key] = first[key]
    return out


# ---- the loopback server ----


class Handler(http.server.BaseHTTPRequestHandler):
    key = ""

    def do_POST(self):
        try:
            if self.headers.get("Authorization") != "Bearer " + self.key:
                raise Refusal(401, "invalid_api_key", "this bridge serves only the imagegen wrapper that started it")
            length = int(self.headers.get("Content-Length") or 0)
            path = self.path.split("?", 1)[0]
            if path == "/v1/images/generations":
                if length > JSON_CAP:
                    raise Refusal(413, "request_too_large", f"request body exceeds {JSON_CAP} bytes")
                try:
                    fields = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    raise Refusal(400, "invalid_json", "request body must be a JSON object") from None
                request = normalise(fields, [], None)
            elif path == "/v1/images/edits":
                if length > EDIT_CAP:
                    raise Refusal(413, "request_too_large", f"request body exceeds {EDIT_CAP} bytes")
                request = normalise(*parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(length)))
            else:
                raise Refusal(404, "not_found", f"{path} is not served here")
            self.answer(200, generate(request))
        except Refusal as r:
            self.refuse(r)
        except Exception as e:  # answer anyway: a dropped connection is one the SDK retries
            self.refuse(Refusal(500, "bridge_error", f"the Codex bridge failed: {e!r}"[:300]))

    def refuse(self, r: Refusal):
        kind = {401: "authentication_error", 429: "rate_limit_error"}.get(r.status)
        kind = kind or ("invalid_request_error" if r.status < 500 else "api_error")
        # The SDK prints this message; the bridge does not print it again.
        self.answer(r.status, {"error": {"message": r.message, "type": kind, "code": r.code}})

    def answer(self, status: int, obj: dict):
        out = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("x-should-retry", "false")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="validate the Codex login and print the host model")
    serve = sub.add_parser("serve", help="serve the Images API on 127.0.0.1")
    serve.add_argument("--port-file", required=True)
    args = ap.parse_args()
    try:
        load_login()
        model = host_model()
    except Refusal as r:
        print(f"imagegen: {r.message}", file=sys.stderr)
        return 1
    if args.cmd == "check":
        print(model)
        return 0
    Handler.key = os.environ.get("IMAGEGEN_CODEX_KEY", "")
    if not Handler.key:
        print("imagegen: IMAGEGEN_CODEX_KEY is unset; the wrapper sets it", file=sys.stderr)
        return 1
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    parent = os.getppid()

    def orphaned():
        # The wrapper stops the bridge when it exits; this covers a wrapper killed outright.
        while os.getppid() == parent:
            time.sleep(2)
        os._exit(0)

    threading.Thread(target=orphaned, daemon=True).start()
    tmp = args.port_file + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(server.server_address[1]))
    os.replace(tmp, args.port_file)  # the wrapper sees the whole port or nothing
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
