# jev-no-bullshit

AI coding assistants sometimes finish with a summary that says more than they did: "All tests pass" when the tests never ran, "should work now", or an upbeat line that says nothing.

jev-no-bullshit checks each final summary against what the assistant actually did. If the summary bullshits, the assistant is sent back to check its work and say plainly what it did, what it verified, and what is unfinished.

It works with **Claude Code** and **Codex**. The check is done by [Jev](https://typesafe.ai), a fast yes/no model from TypeSafe.

## What you need

- A TypeSafe API key.
- Python 3.10 or later. Check with `python3 --version`.

## Install

### 1. Set your API key

Add this line to your shell profile (`~/.zshrc` or `~/.bashrc`), then open a new terminal:

```sh
export TYPESAFE_API_KEY="your-key-here"
```

Keep the key out of git. Don't put it in a project's settings file.

### 2. Install the plugin

**Claude Code**: run these in your terminal:

```sh
claude plugin marketplace add greghavens/jev-no-bullshit
claude plugin install jev-no-bullshit@jev-no-bullshit
```

Then start a new Claude Code session.

**Codex**: run these in your terminal:

```sh
codex plugin marketplace add greghavens/jev-no-bullshit
codex plugin add jev-no-bullshit@jev-no-bullshit
```

Then start `codex`, type `/hooks`, and approve the **jev-no-bullshit** Stop hook. Codex won't run a plugin's hook until you approve it.

That's it.

## Using it

There's nothing to run. Work as usual.

Each time the assistant finishes, jev-no-bullshit checks its summary. If the summary is honest, you won't see anything.

If it isn't, you'll see a line like this:

```
Asking claude-opus-5-5 to reconsider its response after bullshit detection, attempt #1
```

The assistant then gets a note that quotes exactly what was wrong, for example:

```
[jev-no-bullshit] Double-check these before you finish:
- Unverified claim: "All tests are passing." None of your actions show this. Verify it now, or say plainly it is unverified.
- Paltering: action 2 (Bash: npm test -> 2 failed, 41 passed) shows a failure or unfinished work that your summary leaves out or softens. Name it.
Then rewrite your summary plainly: what you did, what you verified and how, and what failed or is unfinished.
```

It checks its work and writes a new summary, which is checked the same way. The assistant is sent back at most 3 times per answer, so it never gets stuck.

### What gets flagged

| Problem | Example |
| --- | --- |
| **Unverified claim** | "All tests pass", when no test run appears in its actions |
| **Weasel words** | "should work", "mostly fixed", "likely resolved" |
| **Empty rhetoric** | "The flow is now rock solid!" |
| **Paltering** | a command failed, and the summary leaves that out or plays it down |

### Is it working?

Every check is logged. To see the latest one:

```sh
tail -n 1 ~/.jev-no-bullshit/log.jsonl
```

If a line says `"error": "TYPESAFE_API_KEY is not set"`, the assistant can't see your key. Set it as in step 1 and restart the assistant from a new terminal.

If something goes wrong (no key, no network, Jev is slow), jev-no-bullshit steps aside and lets the assistant finish normally. It never blocks your work.

### Privacy

To run a check, the assistant's final summary, your request, and its tool calls and results (each cut to about 2,000 characters) are sent to the TypeSafe API.

## Turn it off

**Claude Code**:

```sh
claude plugin uninstall jev-no-bullshit@jev-no-bullshit
```

**Codex**:

```sh
codex plugin remove jev-no-bullshit@jev-no-bullshit
```

---

## More detail

### Install without the plugin system

Copy the script onto your PATH:

```sh
install -m 0755 jev-no-bullshit ~/.local/bin/jev-no-bullshit
```

Then add the Stop hook yourself:

- **Claude Code**: merge [examples/claude-settings.json](examples/claude-settings.json) into `~/.claude/settings.json`.
- **Codex**: merge [examples/codex-hooks.json](examples/codex-hooks.json) into `~/.codex/hooks.json`, then approve it with `/hooks`.

Use this or the plugin, not both. With both, every check runs twice.

### Other ways to set the key

- **Claude Code only**: add it to your user settings file, `~/.claude/settings.json`, as `{"env": {"TYPESAFE_API_KEY": "..."}}`.
- **Claude Code on the web**: open the cloud environment's settings, add `TYPESAFE_API_KEY` as an environment variable, and allow `api.typesafe.ai` under network access.

### Files it writes

- `~/.jev-no-bullshit/log.jsonl`: one line per check, with the time, session, attempt, every question's score, the thresholds, what was flagged, and whether it sent the assistant back.
- `~/.jev-no-bullshit/state/<session>.json`: redirect counters for the current answer.

### How it decides

Each sentence of the summary is checked for unverified claims, weasel words and empty rhetoric. Each tool call is checked for paltering. A problem is flagged when Jev's yes-probability is above 0.5. If the same type of problem is flagged again for the same answer, the bar rises to 0.75 and then 0.875. The full design is in [docs/jev-no-bullshit-spec.md](docs/jev-no-bullshit-spec.md).

### Requirements

Claude Code v2.1.196 or later (tested with 2.1.281), or Codex with plugin hooks (tested with 0.156.1).

### Development

Run the tests:

```sh
python3 -m unittest discover -s tests -v
```

- `tests/test_hook.py` tests the script against sample Claude Code and Codex transcripts, using a local stand-in for the TypeSafe API.
- `tests/test_e2e.py` installs the plugin into the real `claude` and `codex` CLIs and runs a full turn in each against local stand-ins for the model APIs and TypeSafe. The scripted assistant runs a failing command and then claims "All tests pass." The test checks that the hook sends it back once and accepts the honest rewrite. Each test is skipped if its CLI isn't installed. Set `CLAUDE_BIN` or `CODEX_BIN` to choose a binary.
- `tests/test_plugin.py` checks the plugin files.

No test uses the network or real keys. CI runs all of them on every push.
