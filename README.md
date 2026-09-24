# jev-no-bullshit

A Stop hook for Claude Code and Codex. When a turn ends, it asks [Jev](https://typesafe.ai) whether the model's final summary bullshits about what it did, measured against the tool calls it actually made. If Jev flags any of four types (unverified claims, weasel words, empty rhetoric, paltering), the hook sends the model back with feedback that quotes the flagged sentence or action. It does this at most 3 times per turn.

The design is in [docs/jev-no-bullshit-spec.md](docs/jev-no-bullshit-spec.md).

## Install

This repo is a plugin marketplace that both Claude Code and Codex can install from. The plugin adds one Stop hook, which runs `python3 jev-no-bullshit` from the installed copy. You need `python3` on your PATH and a TypeSafe API key (see [API key](#api-key)).

### Claude Code

In Claude Code:

```
/plugin marketplace add greghavens/jev-no-bullshit
/plugin install jev-no-bullshit@jev-no-bullshit
```

Or from a shell:

```sh
claude plugin marketplace add greghavens/jev-no-bullshit
claude plugin install jev-no-bullshit@jev-no-bullshit
```

The hook is active from the next session. It needs Claude Code v2.1.196 or later, for `last_assistant_message`.

### Codex

```sh
codex plugin marketplace add greghavens/jev-no-bullshit
codex plugin add jev-no-bullshit@jev-no-bullshit
```

Codex does not run a plugin's hooks until you trust them. Start `codex`, run `/hooks`, and approve the `jev-no-bullshit` Stop hook. You approve it again if the hook changes in an update.

### Uninstall

```sh
claude plugin uninstall jev-no-bullshit@jev-no-bullshit
codex plugin remove jev-no-bullshit@jev-no-bullshit
```

### Without the plugin system

Copy the script onto your PATH and add the Stop hook yourself:

```sh
install -m 0755 jev-no-bullshit ~/.local/bin/jev-no-bullshit
```

- **Claude Code**: merge [examples/claude-settings.json](examples/claude-settings.json) into `~/.claude/settings.json` (user) or `.claude/settings.json` (project).
- **Codex**: merge [examples/codex-hooks.json](examples/codex-hooks.json) into `~/.codex/hooks.json` or `<repo>/.codex/hooks.json`, then approve it once with `/hooks`.

Use only one of the two methods. With both, the hook runs twice per stop.

## API key

The hook reads `TYPESAFE_API_KEY` from its environment. Keep the key out of this repo and out of project settings files. Use one of these:

- Export it in your shell profile (`~/.zshrc`, `~/.bashrc`): `export TYPESAFE_API_KEY=...`. Both Claude Code and Codex pass their environment through to hooks.
- For Claude Code only, you can put it in your **user** settings instead (`~/.claude/settings.json`, which is not checked in): `{"env": {"TYPESAFE_API_KEY": "..."}}`.
- In Claude Code on the web, add it as an environment variable in the cloud environment's settings. Also allow `api.typesafe.ai` in that environment's network access.

If the key is missing, the hook logs that and lets every turn end. It fails open.

`TYPESAFE_BASE_URL` overrides the API host (default `https://api.typesafe.ai`), as in the official SDK. The tests use it to point at a local mock.

## Wire it up

**Claude Code** (v2.1.196 or later): add [examples/claude-settings.json](examples/claude-settings.json) to `~/.claude/settings.json` (user) or `.claude/settings.json` (project).

**Codex**: add the same content ([examples/codex-hooks.json](examples/codex-hooks.json)) to `~/.codex/hooks.json` or `<repo>/.codex/hooks.json`, then approve it once with `/hooks`.

## What it writes

- `~/.jev-no-bullshit/state/<session_id>.json`: the redirect count and per-type flag counts for the current turn. They reset when `stop_hook_active` is false.
- `~/.jev-no-bullshit/log.jsonl`: one line per check. Each line has the time, session, tool, attempt, every question's `noul`, the thresholds in force, what was flagged, whether it redirected, and the summary. Errors are logged here too.

Summaries, tool inputs and tool results (clipped to about 2,000 characters each) are sent to the TypeSafe API.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

- `tests/test_hook.py` runs the script against Claude Code and Codex transcript fixtures and a local mock of TypeSafe's `POST /v1/systemone`.
- `tests/test_e2e.py` installs this repo as a plugin into the real `claude` and `codex` CLIs, using throwaway config directories. It then runs one headless turn per CLI against local mocks of the Anthropic Messages API, the OpenAI Responses API and TypeSafe. The scripted model runs a failing command and then claims "All tests pass." The test checks that the hook saw the real transcript, redirected once, and let the corrected answer end the turn. Each test is skipped when its CLI is not installed. Set `CLAUDE_BIN` or `CODEX_BIN` to use a specific binary. The Codex test passes `--dangerously-bypass-hook-trust` in place of the `/hooks` approval.

None of the tests use the network or real credentials. CI (`.github/workflows/test.yml`) runs everything against pinned CLI versions.
