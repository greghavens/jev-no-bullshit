"""End-to-end tests: install the plugin into a real Claude Code, Codex, pi or opencode CLI and run a turn.

Each test installs this repo as a plugin marketplace into a throwaway config directory, then runs one
headless turn. The model API and the TypeSafe API are local mocks (tests/mocks.py), so no network or
real credentials are needed. The scripted model runs a failing command, then claims "All tests pass.";
the hook must redirect it once, and the corrected summary must end the turn.

Tests skip when the CLI is not installed. Point them at a specific binary with CLAUDE_BIN, CODEX_BIN, PI_BIN
or OPENCODE_BIN.
Run with: python3 -m unittest tests.test_e2e -v
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mocks import BULLSHIT_SUMMARY, HONEST_SUMMARY, MARKER, MockAnthropic, MockJev, MockResponses  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PLUGIN = "jev-no-bullshit@jev-no-bullshit"
TASK = "Run the tests and tell me whether they pass."

CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
CODEX_BIN = os.environ.get("CODEX_BIN") or shutil.which("codex")
PI_BIN = os.environ.get("PI_BIN") or shutil.which("pi")
OPENCODE_BIN = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")


def flag_bullshit(qid, body):
    """Jev stand-in: flag an unverified claim only for the scripted bullshit sentence."""
    kind, _, index = qid.rpartition("_")
    if kind == "unverified" and body["state"]["sentences"][int(index[1:])] == BULLSHIT_SUMMARY:
        return 0.95
    return 0.05


class _E2EBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.work = root / "work"
        self.home.mkdir()
        self.work.mkdir()
        self.jev = MockJev()
        self.jev.answer = flag_bullshit
        self.env = {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", ""),
            "SHELL": "/bin/sh",
            "LANG": "C.UTF-8",
            "TYPESAFE_API_KEY": "test-key",
            "TYPESAFE_BASE_URL": self.jev.url,
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }

    def tearDown(self):
        self.jev.close()
        self.tmp.cleanup()

    def run_cli(self, args, timeout=180):
        proc = subprocess.run(
            args, cwd=self.work, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout
        )
        self.assertEqual(proc.returncode, 0, f"{args}\nstdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}")
        return proc

    def hook_log(self):
        path = self.home / ".jev-no-bullshit" / "log.jsonl"
        self.assertTrue(path.exists(), "the hook never ran (no log file)")
        return [json.loads(line) for line in path.read_text().splitlines()]

    def assert_one_redirect(self, tool, tool_name):
        log = self.hook_log()
        self.assertEqual(len(log), 2, log)
        first, second = log
        self.assertNotIn("error", first, first)
        self.assertEqual(first["missing_tool_results"], 0, "the hook ran before the tool result reached the transcript")
        self.assertEqual(first["tool"], tool)
        self.assertEqual(first["summary"], BULLSHIT_SUMMARY)
        self.assertEqual(first["flagged"], {"unverified": ["unverified_s0"]})
        self.assertTrue(first["redirected"])
        self.assertEqual(second["attempt"], 1)
        self.assertEqual(second["summary"], HONEST_SUMMARY)
        self.assertFalse(second["redirected"])

        # What Jev saw on the first check, built from the CLI's real transcript.
        state = self.jev.calls[0]["body"]["state"]
        self.assertEqual(state["task"], TASK)
        self.assertEqual(state["sentences"], [BULLSHIT_SUMMARY])
        self.assertEqual(len(state["actions"]), 1, state["actions"])
        action = state["actions"][0]
        self.assertEqual(action["tool"], tool_name)
        self.assertIn("exit 3", action["input"])
        self.assertIn("running tests", action["result"])
        self.assertTrue(action["error"], action)
        # The revision is checked against the same task and actions.
        self.assertEqual(self.jev.calls[1]["body"]["state"]["task"], TASK)
        self.assertEqual(self.jev.schema_errors, [])


@unittest.skipUnless(CLAUDE_BIN, "claude CLI not found (set CLAUDE_BIN)")
class ClaudeCodeE2E(_E2EBase):
    def setUp(self):
        super().setUp()
        self.model = MockAnthropic()
        self.env.update({
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "ANTHROPIC_BASE_URL": self.model.url,
            "ANTHROPIC_API_KEY": "dummy",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        })

    def tearDown(self):
        self.model.close()
        super().tearDown()

    def test_plugin_installs_and_redirects_once(self):
        self.run_cli([CLAUDE_BIN, "plugin", "marketplace", "add", str(REPO)])
        self.run_cli([CLAUDE_BIN, "plugin", "install", PLUGIN])
        listing = self.run_cli([CLAUDE_BIN, "plugin", "list"]).stdout
        self.assertIn(PLUGIN, listing)

        proc = self.run_cli([
            CLAUDE_BIN, "-p", TASK, "--output-format", "json", "--model", "claude-sonnet-5",
            "--allowedTools", "Bash",
        ])
        result = json.loads(proc.stdout)
        self.assertEqual(result.get("result"), HONEST_SUMMARY, result)

        self.assert_one_redirect("claude", "Bash")
        # The model's next request carried the redirect reason.
        requests = self.model.main_loop_requests()
        messages = requests[-1]["body"]["messages"]
        since = max(i for i, m in enumerate(messages) if m.get("role") == "assistant")
        self.assertIn(MARKER, json.dumps(messages[since + 1:]))
        self.assertIn('\\"All tests pass.\\" None of your actions show this.', json.dumps(requests[-1]["body"]))


class ClaudeCodeModuleE2E(ClaudeCodeE2E):
    """The same turn with hooks modules loaded: the module checks, and the plain Stop hook stands down.

    ClaudeCodeE2E runs without them (a mock provider leaves the rollout flag off), so it covers the
    plain Stop hook that stands in where modules do not load.
    """

    def setUp(self):
        super().setUp()
        self.env["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] = "1"


@unittest.skipUnless(CODEX_BIN, "codex CLI not found (set CODEX_BIN)")
class CodexE2E(_E2EBase):
    def setUp(self):
        super().setUp()
        self.model = MockResponses()
        self.env.update({
            "CODEX_HOME": str(self.home / ".codex"),
            "CODEX_SQLITE_HOME": str(self.home / ".codex"),
            "CODEX_API_KEY": "dummy",
        })
        (self.home / ".codex").mkdir()

    def tearDown(self):
        self.model.close()
        super().tearDown()

    def test_plugin_installs_and_redirects_once(self):
        self.run_cli([CODEX_BIN, "plugin", "marketplace", "add", str(REPO)])
        self.run_cli([CODEX_BIN, "plugin", "add", PLUGIN])
        listing = self.run_cli([CODEX_BIN, "plugin", "list"]).stdout
        self.assertIn(PLUGIN, listing)
        self.assertIn("installed, enabled", listing)

        # --dangerously-bypass-hook-trust stands in for approving the hook once with /hooks.
        proc = self.run_cli([
            CODEX_BIN, "exec", "--skip-git-repo-check", "--dangerously-bypass-hook-trust",
            "--dangerously-bypass-approvals-and-sandbox",
            "-c", f"openai_base_url={json.dumps(self.model.url + '/v1')}",
            "-m", "gpt-5.5-codex", TASK,
        ])
        self.assertIn(HONEST_SUMMARY, proc.stdout)

        calls = [item for r in self.model.main_loop_requests() for item in r["body"]["input"]
                 if item.get("type") == "function_call"]
        self.assert_one_redirect("codex", calls[0]["name"])
        last_input = self.model.main_loop_requests()[-1]["body"]["input"]
        self.assertIn(MARKER, json.dumps(last_input[-1]))


@unittest.skipUnless(PI_BIN, "pi CLI not found (set PI_BIN)")
class PiE2E(_E2EBase):
    def setUp(self):
        super().setUp()
        self.model = MockAnthropic()
        agent_dir = self.home / ".pi" / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "models.json").write_text(json.dumps({"providers": {"mock": {
            "baseUrl": self.model.url, "api": "anthropic-messages", "apiKey": "dummy", "models": [{"id": "claude-mock"}],
        }}}))
        self.env.update({"PI_OFFLINE": "1", "PI_TELEMETRY": "0"})

    def tearDown(self):
        self.model.close()
        super().tearDown()

    def test_plugin_installs_and_redirects_once(self):
        # PI_PACKAGE_SOURCE checks an install source as the README gives it, e.g. git:github.com/<owner>/jev-no-bullshit.
        source = os.environ.get("PI_PACKAGE_SOURCE", str(REPO))
        self.run_cli([PI_BIN, "install", source])
        self.assertIn(source, self.run_cli([PI_BIN, "list"]).stdout)

        # Print mode: the feedback continues the same run, so its final text is the revision.
        proc = self.run_cli([PI_BIN, "--print", "--no-session", "--model", "mock/claude-mock", TASK])
        self.assertEqual(proc.stdout.strip(), HONEST_SUMMARY, proc.stderr[-3000:])

        self.assert_one_redirect("pi", "bash")
        messages = self.model.main_loop_requests()[-1]["body"]["messages"]
        self.assertIn(MARKER, json.dumps(messages[-1]))


@unittest.skipUnless(OPENCODE_BIN, "opencode CLI not found (set OPENCODE_BIN)")
class OpencodeE2E(_E2EBase):
    """opencode's server, which its TUI runs on. `opencode run` exits when the session first goes idle,
    before the feedback's turn can start, so the plugin is driven through the server's HTTP API instead."""

    def setUp(self):
        super().setUp()
        self.model = MockAnthropic()
        config = self.home / ".config" / "opencode"
        config.mkdir(parents=True)
        (config / "opencode.json").write_text(json.dumps({
            # OPENCODE_PLUGIN_SPEC checks an install spec as the README gives it, e.g. jev-no-bullshit@git+file://<repo>.
            "plugin": [os.environ.get("OPENCODE_PLUGIN_SPEC", str(REPO))],
            "autoupdate": False,
            "share": "disabled",
            "provider": {"anthropic": {"options": {"baseURL": self.model.url + "/v1", "apiKey": "dummy"}}},
            "permission": {"bash": "allow"},
        }))
        for var, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                         ("XDG_CACHE_HOME", ".cache"), ("XDG_STATE_HOME", ".local/state")):
            self.env[var] = str(self.home / sub)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        self.server = subprocess.Popen(
            [OPENCODE_BIN, "serve", "--port", str(port), "--hostname", "127.0.0.1"], cwd=self.work, env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def tearDown(self):
        self.server.terminate()
        self.server.wait(timeout=10)
        self.model.close()
        super().tearDown()

    def api(self, method, path, body=None):
        request = urllib.request.Request(
            f"{self.base}{path}?directory={self.work}", method=method, headers={"Content-Type": "application/json"},
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def test_plugin_loads_and_redirects_once(self):
        deadline = time.monotonic() + 30
        while True:
            try:
                session = self.api("POST", "/session", {})
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        path = f"/session/{session['id']}/message"
        self.api("POST", path, {"model": {"providerID": "anthropic", "modelID": "claude-sonnet-4-5"},
                                "parts": [{"type": "text", "text": TASK}]})

        # The feedback's turn starts after the first one goes idle; wait for its reply.
        def texts():
            return [(m["info"]["role"], "".join(p.get("text", "") for p in m["parts"] if p["type"] == "text"))
                    for m in self.api("GET", path)]
        deadline = time.monotonic() + 60
        while texts()[-1] != ("assistant", HONEST_SUMMARY) and time.monotonic() < deadline:
            time.sleep(0.3)
        roles = texts()
        self.assertEqual(roles[-1], ("assistant", HONEST_SUMMARY), roles)
        self.assertTrue(roles[-2][1].startswith(MARKER), roles)

        self.assert_one_redirect("opencode", "bash")
        # The shell tool reports a failed command as completed; the plugin adds its exit code.
        self.assertIn("Exit code: 3", self.jev.calls[0]["body"]["state"]["actions"][0]["result"])


if __name__ == "__main__":
    unittest.main()
