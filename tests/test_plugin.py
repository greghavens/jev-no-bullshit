"""Static checks on the plugin layout that Claude Code and Codex both install from."""

import json
import os
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load(relative):
    return json.loads((REPO / relative).read_text())


class PluginLayoutTests(unittest.TestCase):
    def test_marketplace_lists_this_repo_as_the_plugin(self):
        marketplace = load(".claude-plugin/marketplace.json")
        plugin = load(".claude-plugin/plugin.json")
        self.assertEqual(marketplace["name"], "jev-no-bullshit")
        [entry] = marketplace["plugins"]
        self.assertEqual(entry["name"], plugin["name"])
        self.assertEqual(entry["source"], "./")

    def test_stop_hook_runs_the_bundled_script(self):
        hooks = load("hooks/hooks.json")["hooks"]
        self.assertEqual(list(hooks), ["Stop"])
        [group] = hooks["Stop"]
        [handler] = group["hooks"]
        self.assertEqual(handler["type"], "command")
        # Claude Code substitutes ${CLAUDE_PLUGIN_ROOT}; Codex sets it in the hook's environment and runs
        # the command through a shell. Both resolve to the installed copy of this repo.
        self.assertEqual(handler["command"], 'python3 "${CLAUDE_PLUGIN_ROOT}/jev-no-bullshit"')
        self.assertGreater(handler["timeout"], 10)  # above the 10 s Jev timeout, so the hook fails open itself
        script = REPO / "jev-no-bullshit"
        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))

    def test_manual_examples_match_the_plugin_hook(self):
        for name in ("examples/claude-settings.json", "examples/codex-hooks.json"):
            [group] = load(name)["hooks"]["Stop"]
            [handler] = group["hooks"]
            self.assertEqual(handler["command"], "jev-no-bullshit")
            self.assertEqual(handler["timeout"], load("hooks/hooks.json")["hooks"]["Stop"][0]["hooks"][0]["timeout"])

    def test_every_manifest_carries_the_same_version(self):
        versions = {name: load(name)["version"] for name in
                    (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "package.json")}
        self.assertEqual(len(set(versions.values())), 1, versions)

    def test_package_points_pi_and_opencode_at_their_entry_files(self):
        package = load("package.json")
        for entry in [package["main"], *package["pi"]["extensions"]]:
            self.assertTrue((REPO / entry).is_file(), entry)


if __name__ == "__main__":
    unittest.main()
