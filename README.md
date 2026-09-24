# jev-no-bullshit

A Stop hook for Claude Code and Codex. When a turn ends, it asks [Jev](https://typesafe.ai) whether the model's final summary bullshits about what it did, measured against the tool calls it actually made. If Jev flags any of four types (unverified claims, weasel words, empty rhetoric, paltering), the hook sends the model back with feedback that quotes the flagged sentence or action. It does this at most 3 times per turn.

The design is in [docs/jev-no-bullshit-spec.md](docs/jev-no-bullshit-spec.md).

## Install

It is one Python script with no dependencies (tested on Python 3.10 to 3.13).

```sh
install -m 0755 jev-no-bullshit ~/.local/bin/jev-no-bullshit   # any directory on your PATH
```

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
python3 -m unittest discover -s tests
```

The tests run the script against Claude Code and Codex transcript fixtures and a local mock of `POST /v1/systemone`. They make no network calls.
