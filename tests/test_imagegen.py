"""The imagegen wrapper: request shape, model and backend reporting, choosing a backend, the
subscription backend's proxy and login, the codex backend's bridge and Codex login, and refusing to
run without their prerequisites. Everything here is --dry-run, fails before the API, or talks to a
local fake of the proxy or of the ChatGPT backend, so no call is spent."""

import base64
import http.server
import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "imagegen", "scripts")
WRAPPER = os.path.join(SCRIPTS, "imagegen")
IMAGE_GEN = os.path.join(SCRIPTS, "image_gen.py")


def run(cmd, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(), timeout=300)


def payload(stdout):
    return json.loads(stdout[stdout.index("{") :])


class VendoredScript(unittest.TestCase):
    def test_dry_run_builds_a_gpt_image_2_request(self):
        out = os.path.join(tempfile.mkdtemp(), "concept.png")
        r = run(
            [
                "python3",
                IMAGE_GEN,
                "generate",
                "--prompt",
                "a dashboard",
                "--size",
                "1536x1024",
                "--quality",
                "high",
                "--out",
                out,
                "--dry-run",
            ]
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        p = payload(r.stdout)
        self.assertEqual((p["model"], p["size"], p["quality"], p["outputs"]), ("gpt-image-2", "1536x1024", "high", [out]))
        self.assertFalse(os.path.exists(out))

    def test_rejects_an_invalid_gpt_image_2_size(self):
        r = run(["python3", IMAGE_GEN, "generate", "--prompt", "x", "--size", "1000x1000", "--dry-run"])
        self.assertNotEqual(r.returncode, 0)


class Wrapper(unittest.TestCase):
    def test_executable(self):
        self.assertTrue(os.access(WRAPPER, os.X_OK))

    def test_refuses_without_uv(self):
        env = {k: v for k, v in os.environ.items() if k != "PATH"}
        env["PATH"] = "/usr/bin:/bin"
        if shutil.which("uv", path=env["PATH"]):
            self.skipTest("uv is installed in /usr/bin or /bin")
        r = run(["/bin/bash", WRAPPER, "generate", "--prompt", "x", "--dry-run"], env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("uv is not installed", r.stderr)

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_reports_the_model_in_both_flag_forms(self):
        for args, model in (
            (["--model", "gpt-image-1.5"], "gpt-image-1.5"),
            (["--model=gpt-image-1.5"], "gpt-image-1.5"),
            ([], "gpt-image-2"),
        ):
            r = run([WRAPPER, "generate", "--prompt", "x", "--dry-run", *args], env=dict(os.environ, IMAGEGEN_BACKEND="api"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"imagegen: model {model} via ", r.stderr)
            self.assertEqual(payload(r.stdout)["model"], model)

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_a_dry_run_needs_no_proxy(self):
        r = run([WRAPPER, "generate", "--prompt", "x", "--dry-run"], env=dict(without_proxy(), IMAGEGEN_BACKEND="subscription"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(
            "model gpt-image-2-codex (ChatGPT image tool) via ChatGPT subscription (switch proxy none; dry-run only)", r.stderr
        )

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_backend_follows_the_environment_when_unset(self):
        r = run([WRAPPER, "generate", "--prompt", "x", "--dry-run"], env=without_proxy())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("via Codex login (dry-run only; login not read)", r.stderr)
        env = dict(without_proxy(), CLAUDE_SWITCH_PARENT_HTTPS_PROXY="http://127.0.0.1:9")
        r = run([WRAPPER, "generate", "--prompt", "x", "--dry-run"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("via ChatGPT subscription (switch proxy http://127.0.0.1:9)", r.stderr)

    def test_the_chatgpt_backends_refuse_a_model_outside_gpt_image(self):
        for backend in ("codex", "subscription"):
            r = run(
                [WRAPPER, "generate", "--prompt", "x", "--model", "dall-e-3", "--dry-run"],
                env=dict(without_proxy(), IMAGEGEN_BACKEND=backend),
            )
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("--model must be a gpt-image model, not 'dall-e-3'", r.stderr)

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_api_backend_fails_loudly_without_an_api_key(self):
        env = {k: v for k, v in without_proxy().items() if k != "OPENAI_API_KEY"}
        env["IMAGEGEN_BACKEND"] = "api"
        r = run([WRAPPER, "generate", "--prompt", "x", "--out", os.path.join(tempfile.mkdtemp(), "x.png")], env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("via OpenAI API (OPENAI_API_KEY)", r.stderr)
        self.assertIn("OPENAI_API_KEY is not set", r.stderr)

    def test_refuses_an_unknown_backend(self):
        env = dict(os.environ, IMAGEGEN_BACKEND="dalle")
        r = run([WRAPPER, "generate", "--prompt", "x"], env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("IMAGEGEN_BACKEND must be codex, subscription or api", r.stderr)


def without_proxy():
    return {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "CLAUDE_SWITCH_PARENT_HTTPS_PROXY",
            "IMAGEGEN_PROXY_URL",
            "IMAGEGEN_BACKEND",
            "CODEX_HOME",
            "IMAGEGEN_CODEX_MODEL",
        )
    }


def helper_script(text, code=0):
    """A stand-in proxyAuthHelper that prints `text` and exits `code`."""
    path = os.path.join(tempfile.mkdtemp(), "proxy-auth-helper")
    with open(path, "w") as f:
        f.write(f"#!/bin/sh\nprintf '%s\\n' '{text}'\nexit {code}\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


# The smallest valid PNG: 1x1, one opaque pixel.
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class FakeProxy(http.server.BaseHTTPRequestHandler):
    """The switch proxy's Images API route, as far as the SDK can tell: it records what arrived
    and answers one image."""

    seen = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        FakeProxy.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(body or b"{}")})
        out = json.dumps({"created": 1, "data": [{"b64_json": base64.b64encode(PNG_1X1).decode()}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


class SubscriptionBackend(unittest.TestCase):
    def test_refuses_outside_a_switch_session(self):
        r = run([WRAPPER, "generate", "--prompt", "x"], env=dict(without_proxy(), IMAGEGEN_BACKEND="subscription"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("CLAUDE_SWITCH_PARENT_HTTPS_PROXY is unset", r.stderr)

    def test_refuses_a_helper_that_fails_or_prints_no_login(self):
        for helper, said in ((helper_script("x", code=3), "failed"), (helper_script("Bearer abc"), "did not print a 'Basic")):
            env = dict(without_proxy(), IMAGEGEN_PROXY_URL="http://127.0.0.1:9", IMAGEGEN_PROXY_AUTH_HELPER=helper)
            r = run([WRAPPER, "generate", "--prompt", "x"], env=env)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn(said, r.stderr)

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_generates_through_the_proxy_with_the_helpers_login(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeProxy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        FakeProxy.seen = []
        login = base64.b64encode(b"user:secret").decode()
        out = os.path.join(tempfile.mkdtemp(), "x.png")
        env = dict(
            without_proxy(),
            CLAUDE_SWITCH_PARENT_HTTPS_PROXY=f"http://127.0.0.1:{server.server_address[1]}",
            IMAGEGEN_PROXY_AUTH_HELPER=helper_script(f"Basic {login}"),
            OPENAI_API_KEY="sk-must-not-be-sent",
        )
        r = run([WRAPPER, "generate", "--prompt", "a dashboard", "--quality", "low", "--out", out, "--no-augment"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("via ChatGPT subscription (switch proxy http://127.0.0.1:", r.stderr)
        self.assertEqual(len(FakeProxy.seen), 1)
        seen = FakeProxy.seen[0]
        self.assertEqual(seen["path"], "/v1/images/generations")
        self.assertEqual(seen["auth"], f"Bearer {login}")
        self.assertEqual((seen["body"]["model"], seen["body"]["quality"]), ("gpt-image-2", "low"))
        with open(out, "rb") as f:
            self.assertEqual(f.read(), PNG_1X1)


def jwt(exp):
    """An access token shaped like Codex's: only its exp claim is read."""
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc({'exp': exp})}.sig"


def codex_home(auth=None, config='model = "gpt-host-test"\n', cache=None):
    """A CODEX_HOME holding a ChatGPT login (or `auth`), a config.toml and an optional model cache."""
    home = tempfile.mkdtemp()
    if auth is None:
        auth = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {"access_token": jwt(time.time() + 3600), "account_id": "acct-1"},
        }
    if auth is not False:
        with open(os.path.join(home, "auth.json"), "w") as f:
            json.dump(auth, f)
    if config is not None:
        with open(os.path.join(home, "config.toml"), "w") as f:
            f.write(config)
    if cache is not None:
        with open(os.path.join(home, "models_cache.json"), "w") as f:
            json.dump(cache, f)
    return home


class FakeChatGPT(http.server.BaseHTTPRequestHandler):
    """The ChatGPT backend's /backend-api/codex/responses, as far as the bridge can tell. `answer`
    picks what it streams back: an image, a text reply instead, or a quota refusal."""

    seen = []
    answer = "image"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeChatGPT.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if FakeChatGPT.answer == "slow":
            time.sleep(3)
        if FakeChatGPT.answer == "broken":
            # Promise more than is sent, then hang up: the client sees the stream end early.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b'data: {"type": "response.created"}\n')
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        if FakeChatGPT.answer == "ratelimit":
            out = b'{"error": {"message": "slow down"}}'
            self.send_response(429)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if FakeChatGPT.answer == "quota":
            out = json.dumps(
                {
                    "error": {
                        "type": "usage_limit_reached",
                        "message": "The usage limit has been reached",
                        "resets_in_seconds": 600,
                    }
                }
            ).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if FakeChatGPT.answer == "text":
            item = {"type": "message", "content": [{"type": "output_text", "text": "I cannot draw that."}]}
        else:
            item = {
                "type": "image_generation_call",
                "status": "completed",
                "result": base64.b64encode(PNG_1X1).decode(),
                "size": "1024x1024",
                "quality": "low",
                "output_format": "png",
                "background": "opaque",
            }
        events = [
            {"type": "response.output_item.done", "item": item},
            {"type": "response.completed", "response": {"status": "completed"}},
        ]
        out = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("uv"), "needs uv")
class CodexBackend(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeChatGPT)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        FakeChatGPT.seen = []
        FakeChatGPT.answer = "image"
        self.out = os.path.join(tempfile.mkdtemp(), "x.png")

    def env(self, home):
        return dict(
            without_proxy(),
            IMAGEGEN_BACKEND="codex",
            CODEX_HOME=home,
            IMAGEGEN_CODEX_BASE_URL=f"http://127.0.0.1:{self.server.server_address[1]}",
            OPENAI_API_KEY="sk-must-not-be-sent",
        )

    def generate(self, home, *extra):
        return run(
            [
                WRAPPER,
                "generate",
                "--prompt",
                "a dashboard",
                "--quality",
                "low",
                "--size",
                "1024x1024",
                "--out",
                self.out,
                "--no-augment",
                *extra,
            ],
            env=self.env(home),
        )

    def test_generates_with_the_codex_login_on_codexs_model(self):
        r = self.generate(codex_home())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("imagegen: model gpt-image-2-codex (ChatGPT image tool) via Codex login, hosted by gpt-host-test", r.stderr)
        self.assertEqual(len(FakeChatGPT.seen), 1)
        seen = FakeChatGPT.seen[0]
        self.assertEqual(seen["path"], "/backend-api/codex/responses")
        headers = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertTrue(headers["authorization"].startswith("Bearer ") and "sk-must-not-be-sent" not in headers["authorization"])
        self.assertEqual((headers["chatgpt-account-id"], headers["originator"]), ("acct-1", "codex-cli"))
        body = seen["body"]
        self.assertEqual((body["model"], body["stream"], body["store"]), ("gpt-host-test", True, False))
        tool = body["tools"][0]
        self.assertEqual((tool["type"], tool["quality"], tool["size"]), ("image_generation", "low", "1024x1024"))
        self.assertNotIn("model", tool)
        self.assertEqual(body["input"][0]["content"], [{"type": "input_text", "text": "a dashboard"}])
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), PNG_1X1)

    def test_an_edit_sends_its_images_and_mask(self):
        src = os.path.join(tempfile.mkdtemp(), "in.png")
        with open(src, "wb") as f:
            f.write(PNG_1X1)
        r = run(
            [WRAPPER, "edit", "--image", src, "--mask", src, "--prompt", "make it blue", "--out", self.out, "--no-augment"],
            env=self.env(codex_home()),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = FakeChatGPT.seen[0]["body"]
        content = body["input"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["input_text", "input_image"])
        self.assertTrue(content[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertTrue(body["tools"][0]["input_image_mask"]["image_url"].startswith("data:image/png;base64,"))

    def test_the_host_model_comes_from_the_model_cache_without_a_config(self):
        cache = {
            "models": [
                {"slug": "hidden", "visibility": "hide", "priority": 0},
                {"slug": "second", "visibility": "list", "priority": 5},
                {"slug": "first", "visibility": "list", "priority": 1},
            ]
        }
        r = self.generate(codex_home(config=None, cache=cache))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(FakeChatGPT.seen[0]["body"]["model"], "first")

    def test_refuses_without_a_chatgpt_login_and_calls_nothing(self):
        api_key_login = {"auth_mode": "apikey", "OPENAI_API_KEY": "sk-x", "tokens": None}
        expired = {"auth_mode": "chatgpt", "tokens": {"access_token": jwt(time.time() - 60), "account_id": "acct-1"}}
        for auth, said in (
            (False, "no Codex login at"),
            (api_key_login, "signed in with an API key"),
            (expired, "the Codex login expired at"),
        ):
            r = self.generate(codex_home(auth=auth))
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn(said, r.stderr)
        self.assertEqual(FakeChatGPT.seen, [])

    def test_a_quota_refusal_fails_once_without_retrying(self):
        FakeChatGPT.answer = "quota"
        r = self.generate(codex_home())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage limit is reached", r.stderr)
        self.assertEqual(len(FakeChatGPT.seen), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_a_successful_run_reports_no_stray_job_lines(self):
        r = self.generate(codex_home())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Terminated", r.stderr)

    def test_an_error_is_reported_once(self):
        FakeChatGPT.answer = "quota"
        r = self.generate(codex_home())
        self.assertEqual(r.stderr.count("usage limit is reached"), 1, r.stderr)

    def test_a_rate_limit_is_not_reported_as_the_plan_limit(self):
        FakeChatGPT.answer = "ratelimit"
        r = self.generate(codex_home())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("asked us to slow down", r.stderr)
        self.assertNotIn("usage limit", r.stderr)
        self.assertEqual(len(FakeChatGPT.seen), 1)

    def test_a_broken_stream_fails_once_without_retrying(self):
        FakeChatGPT.answer = "broken"
        r = self.generate(codex_home())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("stream ended early", r.stderr)
        self.assertEqual(len(FakeChatGPT.seen), 1)

    def test_a_request_past_the_deadline_fails_once_without_retrying(self):
        FakeChatGPT.answer = "slow"
        env = dict(self.env(codex_home()), IMAGEGEN_CODEX_DEADLINE="1")
        r = run([WRAPPER, "generate", "--prompt", "x", "--out", self.out, "--no-augment"], env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ran past the bridge's 1 s limit", r.stderr)
        self.assertEqual(len(FakeChatGPT.seen), 1)

    def test_an_edit_takes_several_images_and_refuses_a_mask_that_is_not_png(self):
        src = os.path.join(tempfile.mkdtemp(), "in.png")
        with open(src, "wb") as f:
            f.write(PNG_1X1)
        r = run(
            [WRAPPER, "edit", "--image", src, "--image", src, "--prompt", "combine", "--out", self.out, "--no-augment"],
            env=self.env(codex_home()),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        content = FakeChatGPT.seen[0]["body"]["input"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["input_text", "input_image", "input_image"])
        jpeg = os.path.join(tempfile.mkdtemp(), "mask.jpg")
        with open(jpeg, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\0" * 64)
        r = run(
            [WRAPPER, "edit", "--image", src, "--mask", jpeg, "--prompt", "x", "--out", self.out + "2", "--no-augment"],
            env=self.env(codex_home()),
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mask", r.stderr.lower())
        self.assertEqual(len(FakeChatGPT.seen), 1)

    def test_a_text_answer_is_an_error_that_says_why(self):
        FakeChatGPT.answer = "text"
        r = self.generate(codex_home())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("answered with text instead of calling the image tool: I cannot draw that.", r.stderr)


if __name__ == "__main__":
    unittest.main()
