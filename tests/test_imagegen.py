"""The imagegen wrapper: request shape, model and backend reporting, choosing a backend, the
subscription backend's proxy and login and what the proxy says drew each image, the codex backend's
bridge and Codex login, and refusing to run without their prerequisites. Everything here is
--dry-run, fails before the API, or talks to a local fake of the proxy or of the ChatGPT backend,
so no call is spent."""

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
        self.assertIn("imagegen: via switch proxy none (dry-run only); it picks the provider and model for each image", r.stderr)

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_backend_follows_the_environment_when_unset(self):
        r = run([WRAPPER, "generate", "--prompt", "x", "--dry-run"], env=without_proxy())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("via Codex login (dry-run only; login not read)", r.stderr)
        env = dict(without_proxy(), CLAUDE_SWITCH_PARENT_HTTPS_PROXY="http://127.0.0.1:9")
        r = run([WRAPPER, "generate", "--prompt", "x", "--dry-run"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("imagegen: via switch proxy http://127.0.0.1:9;", r.stderr)

    def test_the_chatgpt_backends_refuse_a_callers_model(self):
        """codex and the switch proxy choose the model; a caller names a class, never a model."""
        for backend in ("codex", "subscription"):
            for args in (["--model", "gpt-image-2"], ["--model=gpt-image-1.5"], ["--model", "dall-e-3"], ["--model"]):
                with self.subTest(backend=backend, args=args):
                    r = run(
                        [WRAPPER, "generate", "--prompt", "x", "--dry-run", *args],
                        env=dict(without_proxy(), IMAGEGEN_BACKEND=backend),
                    )
                    self.assertEqual(r.returncode, 1, r.stderr)
                    self.assertEqual(
                        r.stderr,
                        f"imagegen: --model is not taken on the {backend} backend, which chooses the model itself; "
                        "on the switch proxy, name an image class with --class (images, images-runway, images-chatgpt)\n",
                    )
                    self.assertEqual(r.stdout, "")

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_chatgpt_backends_pass_a_transparent_background_through(self):
        """The vendored script lets transparency through only with gpt-image-1.5; the wrapper supplies it."""
        for backend in ("codex", "subscription"):
            for args in (["--background", "transparent"], ["--background=transparent"]):
                with self.subTest(backend=backend, args=args):
                    r = run(
                        [WRAPPER, "generate", "--prompt", "x", "--dry-run", "--output-format", "png", *args],
                        env=dict(without_proxy(), IMAGEGEN_BACKEND=backend),
                    )
                    self.assertEqual(r.returncode, 0, r.stderr)
                    p = payload(r.stdout)
                    self.assertEqual((p["background"], p["model"]), ("transparent", "gpt-image-1.5"))

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_api_backend_still_needs_its_model_for_transparency(self):
        r = run(
            [WRAPPER, "generate", "--prompt", "x", "--dry-run", "--background", "transparent", "--output-format", "png"],
            env=dict(without_proxy(), IMAGEGEN_BACKEND="api"),
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("transparent backgrounds are not supported in gpt-image-2", r.stderr)

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_api_backend_fails_loudly_without_an_api_key(self):
        env = {k: v for k, v in without_proxy().items() if k != "OPENAI_API_KEY"}
        env["IMAGEGEN_BACKEND"] = "api"
        r = run([WRAPPER, "generate", "--prompt", "x", "--out", os.path.join(tempfile.mkdtemp(), "x.png")], env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("via OpenAI API (OPENAI_API_KEY)", r.stderr)
        self.assertIn("OPENAI_API_KEY is not set", r.stderr)

    def test_a_class_outside_the_switch_proxy_is_an_error(self):
        for backend in ("codex", "api"):
            for args, env in (
                (["--class", "images-runway"], {}),
                (["--class=images-runway"], {}),
                ([], {"IMAGEGEN_CLASS": "images-runway"}),
            ):
                with self.subTest(backend=backend, args=args, env=env):
                    r = run(
                        [WRAPPER, "generate", "--prompt", "x", "--dry-run", *args],
                        env=dict(without_proxy(), IMAGEGEN_BACKEND=backend, **env),
                    )
                    self.assertEqual(r.returncode, 1, r.stderr)
                    self.assertIn("image classes exist only under the switch proxy", r.stderr)
                    self.assertIn(f"this backend is {backend}:", r.stderr)

    def test_a_class_flag_needs_a_name(self):
        for args in (["--class"], ["--class="], ["--class", "a b"]):
            with self.subTest(args=args):
                r = run(
                    [WRAPPER, "generate", "--prompt", "x", "--dry-run", *args],
                    env=dict(without_proxy(), IMAGEGEN_BACKEND="subscription"),
                )
                self.assertEqual(r.returncode, 1, r.stderr)

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_class_flag_never_reaches_the_vendored_script(self):
        """image_gen.py rejects flags it does not know; the wrapper takes --class out wherever it is."""
        for args in (
            ["--class", "images-runway", "generate", "--prompt", "x", "--dry-run", "--no-augment"],
            ["generate", "--class", "images-runway", "--prompt", "x", "--dry-run", "--no-augment"],
            ["generate", "--prompt", "x", "--dry-run", "--no-augment", "--class=images-runway"],
        ):
            with self.subTest(args=args):
                r = run([WRAPPER, *args], env=dict(without_proxy(), IMAGEGEN_BACKEND="subscription"))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("imagegen: via switch proxy none (dry-run only), class images-runway;", r.stderr)
                self.assertEqual(payload(r.stdout)["prompt"], "x")

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_models_outside_the_switch_proxy_names_the_one_provider(self):
        for backend, said in (("codex", "Codex login"), ("api", "OPENAI_API_KEY")):
            with self.subTest(backend=backend):
                r = run([WRAPPER, "models"], env=dict(without_proxy(), IMAGEGEN_BACKEND=backend))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f"backend {backend}:", r.stdout)
                self.assertIn(said, r.stdout)
                self.assertIn("It has one provider", r.stdout)
                self.assertIn("exist only under the switch proxy", r.stdout)

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
            "IMAGEGEN_CLASS",
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
    """The switch proxy's Images API routes, as far as the SDK can tell: it records what arrived
    and answers the `n` images asked for. `drawn`, given the JSON body ({} for an edit's form),
    returns the X-Switch-Member and X-Switch-Funding values that name what drew them, or None to
    answer without either."""

    seen = []
    drawn = None
    # What GET /v1/models answers: (status, JSON body).
    models = (200, {"object": "list", "data": []})

    def do_GET(self):
        FakeProxy.seen.append(
            {"path": self.path, "auth": self.headers.get("Authorization"), "class": self.headers.get("X-Switch-Class")}
        )
        status, body = FakeProxy.models if self.path == "/v1/models" else (404, {"error": {"message": "no such route"}})
        out = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.loads(raw) if self.headers.get("Content-Type", "").startswith("application/json") else {}
        FakeProxy.seen.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "class": self.headers.get("X-Switch-Class"),
                "body": body,
            }
        )
        image = {"b64_json": base64.b64encode(PNG_1X1).decode()}
        out = json.dumps({"created": 1, "data": [image] * body.get("n", 1)}).encode()
        drawn = FakeProxy.drawn(body) if FakeProxy.drawn else None
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if drawn:
            self.send_header("X-Switch-Member", drawn[0])
            self.send_header("X-Switch-Funding", drawn[1])
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

    @unittest.skipIf(os.path.exists("/opt/claude-switch/proxy-auth-helper"), "a cloud session's helper comes first")
    def test_finds_the_apiary_helper_in_home(self):
        home = tempfile.mkdtemp()
        env = dict(without_proxy(), HOME=home, IMAGEGEN_PROXY_URL="http://127.0.0.1:9")
        env.pop("IMAGEGEN_PROXY_AUTH_HELPER", None)
        r = run([WRAPPER, "generate", "--prompt", "x"], env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("~/.apiary/proxy-auth-helper); set IMAGEGEN_PROXY_AUTH_HELPER", r.stderr)
        os.makedirs(os.path.join(home, ".apiary"))
        shutil.copy(helper_script("x", code=3), os.path.join(home, ".apiary", "proxy-auth-helper"))
        r = run([WRAPPER, "generate", "--prompt", "x"], env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(f"imagegen: {home}/.apiary/proxy-auth-helper failed", r.stderr)


@unittest.skipUnless(shutil.which("uv"), "needs uv")
class SubscriptionProxy(unittest.TestCase):
    """Calls through a fake of the switch proxy, which picks what draws each image and names it."""

    def setUp(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeProxy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        FakeProxy.seen, FakeProxy.drawn, FakeProxy.models = [], None, (200, {"object": "list", "data": []})
        self.login = base64.b64encode(b"user:secret").decode()
        self.dir = tempfile.mkdtemp()
        self.env = dict(
            without_proxy(),
            CLAUDE_SWITCH_PARENT_HTTPS_PROXY=f"http://127.0.0.1:{server.server_address[1]}",
            IMAGEGEN_PROXY_AUTH_HELPER=helper_script(f"Basic {self.login}"),
            OPENAI_API_KEY="sk-must-not-be-sent",
        )

    def generate(self, *args):
        return run([WRAPPER, "generate", "--prompt", "a dashboard", "--quality", "low", "--no-augment", *args], env=self.env)

    def test_generates_through_the_proxy_with_the_helpers_login(self):
        FakeProxy.drawn = lambda body: ("runway/gpt_image_2", "paid:runway/balance")
        out = os.path.join(self.dir, "x.png")
        r = self.generate("--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("imagegen: via switch proxy http://127.0.0.1:", r.stderr)
        self.assertIn(f"imagegen: {out} drawn by runway/gpt_image_2 (paid:runway/balance)\n", r.stderr)
        self.assertEqual(len(FakeProxy.seen), 1)
        seen = FakeProxy.seen[0]
        self.assertEqual(seen["path"], "/v1/images/generations")
        self.assertEqual(seen["auth"], f"Bearer {self.login}")
        self.assertEqual((seen["body"]["model"], seen["body"]["quality"]), ("gpt-image-2", "low"))
        with open(out, "rb") as f:
            self.assertEqual(f.read(), PNG_1X1)

    def test_each_image_names_what_drew_it_in_order(self):
        FakeProxy.drawn = lambda body: ("gpt/gpt-image-2,runway/gpt_image_2", "included,paid:runway/balance")
        r = self.generate("--n", "2", "--out", os.path.join(self.dir, "x.png"))
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second = (os.path.join(self.dir, f"x-{i}.png") for i in (1, 2))
        self.assertIn(f"imagegen: {first} drawn by gpt/gpt-image-2 (included)\n", r.stderr)
        self.assertIn(f"imagegen: {second} drawn by runway/gpt_image_2 (paid:runway/balance)\n", r.stderr)

    def test_an_image_written_before_a_later_one_fails_is_still_named(self):
        """Both images were drawn (and paid for) before the second's output turned out to exist."""
        FakeProxy.drawn = lambda body: ("gpt/gpt-image-2,runway/gpt_image_2", "included,paid:runway/balance")
        first, second = (os.path.join(self.dir, f"x-{i}.png") for i in (1, 2))
        with open(second, "wb") as f:
            f.write(b"already here")
        r = self.generate("--n", "2", "--out", os.path.join(self.dir, "x.png"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Output already exists", r.stderr)
        self.assertIn(f"imagegen: {first} drawn by gpt/gpt-image-2 (included)\n", r.stderr)
        self.assertNotIn(f"imagegen: {second} drawn by", r.stderr)

    def test_an_edit_names_what_drew_it(self):
        FakeProxy.drawn = lambda body: ("runway/gpt_image_2", "paid:runway/balance")
        src, out = os.path.join(self.dir, "in.png"), os.path.join(self.dir, "out.png")
        with open(src, "wb") as f:
            f.write(PNG_1X1)
        r = run([WRAPPER, "edit", "--image", src, "--prompt", "make it blue", "--out", out, "--no-augment"], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(FakeProxy.seen[0]["path"], "/v1/images/edits")
        self.assertIn(f"imagegen: {out} drawn by runway/gpt_image_2 (paid:runway/balance)\n", r.stderr)

    def test_each_batch_job_names_what_drew_its_own_image(self):
        """Two jobs in flight at once: each image is named with its own job's answer."""
        FakeProxy.drawn = lambda body: (
            ("gpt/gpt-image-2", "included") if body["prompt"] == "first" else ("runway/gpt_image_2", "paid:runway/balance")
        )
        jobs = os.path.join(self.dir, "jobs.jsonl")
        with open(jobs, "w") as f:
            f.write(json.dumps({"prompt": "first", "out": "first.png"}) + "\n")
            f.write(json.dumps({"prompt": "second", "out": "second.png"}) + "\n")
        r = run(
            [WRAPPER, "generate-batch", "--input", jobs, "--out-dir", self.dir, "--concurrency", "2", "--no-augment"],
            env=self.env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(FakeProxy.seen), 2)
        first, second = (os.path.join(self.dir, name) for name in ("first.png", "second.png"))
        self.assertIn(f"imagegen: {first} drawn by gpt/gpt-image-2 (included)\n", r.stderr)
        self.assertIn(f"imagegen: {second} drawn by runway/gpt_image_2 (paid:runway/balance)\n", r.stderr)

    def test_a_transparent_picture_reaches_the_proxy_with_its_class(self):
        r = self.generate(
            "--class",
            "images-chatgpt",
            "--background",
            "transparent",
            "--output-format",
            "png",
            "--out",
            os.path.join(self.dir, "x.png"),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        seen = FakeProxy.seen[0]
        self.assertEqual(seen["class"], "images-chatgpt")
        self.assertEqual((seen["body"]["background"], seen["body"]["model"]), ("transparent", "gpt-image-1.5"))

    def test_no_class_sends_no_class_header(self):
        r = self.generate("--out", os.path.join(self.dir, "x.png"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNone(FakeProxy.seen[0]["class"])

    def test_the_class_flag_reaches_the_proxy_as_its_header(self):
        r = self.generate("--class", "images-runway", "--out", os.path.join(self.dir, "x.png"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(", class images-runway;", r.stderr)
        self.assertEqual(FakeProxy.seen[0]["class"], "images-runway")
        self.assertNotIn("class", FakeProxy.seen[0]["body"])

    def test_the_class_from_the_environment_reaches_the_proxy_and_the_flag_wins(self):
        self.env["IMAGEGEN_CLASS"] = "images-chatgpt"
        r = self.generate("--out", os.path.join(self.dir, "x.png"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(FakeProxy.seen[0]["class"], "images-chatgpt")
        r = self.generate("--class=images-runway", "--out", os.path.join(self.dir, "y.png"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(FakeProxy.seen[1]["class"], "images-runway")

    def test_an_edit_and_a_batch_carry_the_class(self):
        src = os.path.join(self.dir, "in.png")
        with open(src, "wb") as f:
            f.write(PNG_1X1)
        r = run(
            [
                WRAPPER,
                "edit",
                "--image",
                src,
                "--prompt",
                "x",
                "--out",
                os.path.join(self.dir, "e.png"),
                "--no-augment",
                "--class",
                "images-runway",
            ],
            env=self.env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        jobs = os.path.join(self.dir, "jobs.jsonl")
        with open(jobs, "w") as f:
            f.write(json.dumps({"prompt": "first", "out": "first.png"}) + "\n")
        r = run(
            [WRAPPER, "generate-batch", "--input", jobs, "--out-dir", self.dir, "--no-augment", "--class", "images-runway"],
            env=self.env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            [(s["path"], s["class"]) for s in FakeProxy.seen],
            [("/v1/images/edits", "images-runway"), ("/v1/images/generations", "images-runway")],
        )

    MODELS = {
        "object": "list",
        "data": [
            {
                "id": "images",
                "object": "model",
                "default": True,
                "summary": "runway/gpt_image_2 can draw now, paid from runway/balance",
                "accepts": {"summary": "sizes both members draw; no mask", "sizes": ["1024x1024"]},
                "members": [
                    {
                        "id": "gpt/gpt-image-2",
                        "check": "no",
                        "summary": "blocked: the ChatGPT plan does not include images",
                        "accepts": {"summary": "any size to 3:1, mask, png/jpeg/webp"},
                    },
                    {
                        "id": "runway/gpt_image_2",
                        "check": "paid",
                        "summary": "paid from runway/balance ($4.20)",
                        "accepts": {"summary": "its own sizes, png only, no mask"},
                        "extra": "ignored",
                    },
                ],
            },
            # A row missing its default, summary and accepts, and a member missing its check and
            # accepts: printed without them.
            {"id": "images-runway", "members": [{"id": "runway/gpt_image_2", "summary": "paid from runway/balance"}]},
            {"id": "images-chatgpt", "default": False, "summary": "nobody can draw now"},
        ],
    }

    def test_models_lists_each_class_with_its_members(self):
        FakeProxy.models = (200, self.MODELS)
        r = run([WRAPPER, "models"], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout,
            "images (default): runway/gpt_image_2 can draw now, paid from runway/balance\n"
            "  accepts: sizes both members draw; no mask\n"
            "  - gpt/gpt-image-2 [no]: blocked: the ChatGPT plan does not include images\n"
            "    accepts: any size to 3:1, mask, png/jpeg/webp\n"
            "  - runway/gpt_image_2 [paid]: paid from runway/balance ($4.20)\n"
            "    accepts: its own sizes, png only, no mask\n"
            "\n"
            "images-runway\n"
            "  - runway/gpt_image_2: paid from runway/balance\n"
            "\n"
            "images-chatgpt: nobody can draw now\n",
        )
        self.assertEqual(FakeProxy.seen, [{"path": "/v1/models", "auth": f"Bearer {self.login}", "class": None}])

    def test_models_for_one_class(self):
        FakeProxy.models = (200, self.MODELS)
        r = run([WRAPPER, "models", "--class", "images-chatgpt"], env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "images-chatgpt: nobody can draw now\n")
        r = run([WRAPPER, "models", "--class", "images-nope"], env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the proxy lists no class images-nope", r.stderr)

    def test_models_reports_a_refusal_in_the_proxys_words(self):
        for status, said in ((401, "answered 401: bad login"), (404, "this proxy has no image model list")):
            with self.subTest(status=status):
                FakeProxy.models = (status, {"error": {"message": "bad login"}})
                r = run([WRAPPER, "models"], env=self.env)
                self.assertEqual(r.returncode, 1)
                self.assertIn(said, r.stderr)

    def test_an_answer_without_the_headers_names_nothing(self):
        out = os.path.join(self.dir, "x.png")
        r = self.generate("--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("drawn by", r.stderr)
        with open(out, "rb") as f:
            self.assertEqual(f.read(), PNG_1X1)


class FakeUnavailableProxy(http.server.BaseHTTPRequestHandler):
    """The switch proxy's image door when the class `images` has no member that can serve
    (quota-model C3/C4): the class-unavailable reply on the OpenAI wire, exactly as the proxy
    renders it (renderUnavailable). `answer` is "later" (retryable: 429 rate_limit_exceeded with
    Retry-After to the codex reset), "unknown" (retryable with no time known, a brain down past
    stale_max: the same 429 with no Retry-After) or "money" (only money would open it: 429
    insufficient_quota with x-should-retry: false)."""

    seen = []
    answer = "later"
    MESSAGE = "class images is unavailable: gpt is spent until 2026-11-02T00:00:00Z"

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        FakeUnavailableProxy.seen.append(self.path)
        later = FakeUnavailableProxy.answer in ("later", "unknown")
        code = "rate_limit_exceeded" if later else "insufficient_quota"
        err = {"message": self.MESSAGE, "type": "requests" if later else "insufficient_quota", "param": None, "code": code}
        out = json.dumps({"error": err, "unavailable": {"members": [], "options": []}}).encode()
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Switch-Quota", "exhausted")
        self.send_header("X-Switch-Class", "images")
        if FakeUnavailableProxy.answer == "later":
            self.send_header("Retry-After", "187200")
            self.send_header("X-Switch-Available-At", "2026-11-02T00:00:00Z")
        elif later:
            self.send_header("X-Switch-Available-At", "unknown")
        else:
            self.send_header("X-Switch-Available-At", "unknown")
            self.send_header("x-should-retry", "false")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("uv"), "needs uv")
class SubscriptionUnavailable(unittest.TestCase):
    """What the wrapper does with the proxy's one unavailable reply: it fails with the reply's
    words and writes nothing, and never waits out a reset hours away. Every call here is answered
    from the proxy's check, so a retry spends no image."""

    def setUp(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeUnavailableProxy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        FakeUnavailableProxy.seen = []
        self.dir = tempfile.mkdtemp()
        self.env = dict(
            without_proxy(),
            CLAUDE_SWITCH_PARENT_HTTPS_PROXY=f"http://127.0.0.1:{server.server_address[1]}",
            IMAGEGEN_PROXY_AUTH_HELPER=helper_script("Basic " + base64.b64encode(b"user:secret").decode()),
        )

    def generate(self, answer):
        FakeUnavailableProxy.answer = answer
        out = os.path.join(self.dir, "x.png")
        started = time.monotonic()
        r = run([WRAPPER, "generate", "--prompt", "x", "--out", out, "--no-augment"], env=self.env)
        return r, time.monotonic() - started, out

    def test_the_money_reply_fails_once(self):
        r, _, out = self.generate("money")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(FakeUnavailableProxy.MESSAGE, r.stderr)
        self.assertEqual(len(FakeUnavailableProxy.seen), 1, "x-should-retry: false is obeyed")
        self.assertFalse(os.path.exists(out))

    def test_the_retryable_reply_fails_in_seconds_with_its_reset(self):
        """Retry-After is days away: the SDK never sleeps on it, and the reply's message is the
        error."""
        r, took, out = self.generate("later")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(FakeUnavailableProxy.MESSAGE, r.stderr)
        self.assertEqual(len(FakeUnavailableProxy.seen), 1)
        self.assertLess(took, 60, "a reset days away is never slept on")
        self.assertFalse(os.path.exists(out))

    def test_the_retryable_reply_with_no_time_fails_after_the_sdks_own_backoff(self):
        """No time known and no Retry-After: the SDK retries on its own short schedule (each
        retry answered by the proxy's check, so none spends an image), then fails with the
        reply's message."""
        r, took, out = self.generate("unknown")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(FakeUnavailableProxy.MESSAGE, r.stderr)
        self.assertGreater(len(FakeUnavailableProxy.seen), 1, "a retryable reply is retried")
        self.assertLessEqual(len(FakeUnavailableProxy.seen), 3)
        self.assertLess(took, 60)
        self.assertFalse(os.path.exists(out))

    def test_a_batch_fails_its_jobs_and_ends(self):
        """The vendored batch loop retries any 429 --max-attempts times (default 3) on a short
        backoff, the money reply included; it is left verbatim (SKILL.md), and those retries are
        answered by the proxy's check without a dial. Bounded: three calls, seconds; nine for a
        reply with no time, which the SDK also retries on its own (three tries an attempt)."""
        jobs = os.path.join(self.dir, "jobs.jsonl")
        with open(jobs, "w") as f:
            f.write(json.dumps({"prompt": "x"}) + "\n")
        for answer in ("money", "later", "unknown"):
            with self.subTest(answer):
                FakeUnavailableProxy.answer, FakeUnavailableProxy.seen = answer, []
                started = time.monotonic()
                r = run([WRAPPER, "generate-batch", "--input", jobs, "--out-dir", self.dir, "--no-augment"], env=self.env)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(FakeUnavailableProxy.MESSAGE, r.stderr)
                self.assertLessEqual(len(FakeUnavailableProxy.seen), 9 if answer == "unknown" else 3)
                self.assertLess(time.monotonic() - started, 60)
                self.assertEqual([p for p in os.listdir(self.dir) if p.endswith(".png")], [])


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
