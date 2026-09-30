# jev-no-bullshit

AI coding assistants sometimes finish with a summary that says more than they did: "All tests pass" when the tests never ran, "should work now", or a failed command left out.

That's bullshit in the philosopher Harry Frankfurt's sense: statements made without regard to whether they're true. [Machine Bullshit (Liang et al., 2025)](https://arxiv.org/abs/2507.07484) found it in large language models and sorted it into four forms: unverified claims, weasel words, empty rhetoric and paltering. jev-no-bullshit checks for three of them. Empty rhetoric was dropped in v0.5: in real sessions it almost never came up.

jev-no-bullshit checks each final summary against what the assistant actually did. If the summary bullshits, the assistant is sent back to check its work and say plainly what it did, what it verified, and what is unfinished.

It works with **Claude Code**, **Codex**, **pi** and **opencode**. The check is done by [Jev](https://typesafe.ai), a yes/no model from TypeSafe.

## What you need

- A TypeSafe API key.
- Python 3.10 or later. Check with `python3 --version`.
- For pi or opencode, `git` too.

## Install

### 1. Set your API key

Put the key in `~/.config/jev-no-bullshit/env`, readable only by you:

```sh
mkdir -p ~/.config/jev-no-bullshit
printf 'TYPESAFE_API_KEY=%s\n' "your-key-here" > ~/.config/jev-no-bullshit/env
chmod 600 ~/.config/jev-no-bullshit/env
```

The plugin reads this file itself, however the assistant was started. A key here is used only by this plugin, and it wins over a `TYPESAFE_API_KEY` set in your environment or in Claude Code's settings for other tools. Don't source it from your shell profile or write `export` in it, or the key ends up in every program's environment; a line with `export` is refused and the reply goes unchecked. Keep the key out of git. Don't put it in a project's settings file.

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

**pi**: run this in your terminal:

```sh
pi install git:github.com/greghavens/jev-no-bullshit
```

Then start a new pi session.

**opencode**: run this in your terminal:

```sh
opencode plugin -g "jev-no-bullshit@git+https://github.com/greghavens/jev-no-bullshit.git"
```

Then start a new opencode session.

That's it.

## Using it

There's nothing to run. Work as usual.

Each time the assistant finishes, its summary is checked. If the summary is honest, you won't see anything. If it isn't, the assistant gets a note that quotes what was wrong, for example:

```
[jev-no-bullshit] Double-check these before you finish:
- Unverified claim: "All tests are passing." Check this against your recorded actions and results. Correct it or say what remains unverified.
- Paltering: action 2 (Bash: npm test -> 2 failed, 41 passed) shows a failure or unfinished work that your summary leaves out or softens. Name it.
Then rewrite your summary plainly: what you did, what you verified and how, and what failed or is unfinished.
```

The assistant checks its work and writes a new summary, which is checked the same way. By default it's sent back only once per request, and each sentence or action is called out only once per request.

Where you see the note:

- **Claude Code**: below the flagged reply, as a prompt that Claude Code labels as coming from the plugin. If you type a message while the assistant is still working, the note is dropped.
- **Codex**: as Stop hook feedback, after a line like `Asking gpt-6-astra to reconsider its response after bullshit detection, attempt #1`.
- **pi**: as a **jev-no-bullshit** message below the flagged reply. The assistant answers it in the same run.
- **opencode**: as a new prompt below the flagged reply, which starts a turn of its own. `opencode run` exits when the assistant first finishes, before that turn can start, so one-shot runs are checked but not sent back.

### What gets flagged

Three forms of bullshit from the paper:

| Problem | Example |
| --- | --- |
| **Unverified claim** | "All tests pass", when no test run appears in its actions |
| **Weasel words** | "should work", "mostly fixed", "likely resolved" |
| **Paltering** | a command failed, and the summary leaves that out or plays it down |

### Is it working?

Every check is logged. To see the latest one:

```sh
tail -n 1 ~/.jev-no-bullshit/log.jsonl
```

When a check can't run, you're told on screen: Codex shows a warning below the reply, and Claude Code pins it on the status line under the prompt until a check succeeds. The message starts with `jev-no-bullshit did not check this reply`.

If it says `TYPESAFE_API_KEY is not set`, the assistant can't see your key. Set it as in step 1 and restart the assistant from a new terminal. If you start Claude Code some other way than from a terminal, see [Other ways to set the key](#other-ways-to-set-the-key).

If jev-no-bullshit itself runs into a problem (no key, no network, Jev takes more than 10 seconds), it logs the problem, shows the warning above, and lets the assistant finish normally. A problem with the check never holds up your work.

### Privacy

To run a check, the assistant's final summary, your request (cut to about 1,500 characters), the last two messages before the reply, and the tool calls of this turn are sent to the TypeSafe API. Each tool call's input is cut to about 200 characters and its result to about 600, plus lines holding numbers or code terms your summary cites. Some older messages and earlier tool calls are also sent, as one short line each, when they bear on a sentence being checked. When there is nothing worth checking, nothing is sent.

## Turn it off

**Claude Code**:

```sh
claude plugin uninstall jev-no-bullshit@jev-no-bullshit
```

**Codex**:

```sh
codex plugin remove jev-no-bullshit@jev-no-bullshit
```

**pi**:

```sh
pi remove git:github.com/greghavens/jev-no-bullshit
```

**opencode**: delete the `jev-no-bullshit@…` line from `plugin` in `~/.config/opencode/opencode.jsonc` (or `opencode.json`, whichever you have).

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

### If Claude Code shows "Stop hook error"

Showing the note as a prompt uses Claude Code's plugin hook modules, which are in early access. They stay off with a third-party model provider (Bedrock, Vertex, a custom `ANTHROPIC_BASE_URL`), with nonessential traffic disabled, or on accounts the rollout hasn't reached. Set `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` to turn them on anyway. Without them, replies are still checked, but Claude Code shows the note as "Stop hook feedback" under a "Stop hook error" row.

### Call out the same thing more than once

By default, once a sentence or action has been called out, it isn't called out again for the same request, even if a later reply repeats the sentence or leaves the failure out again. To allow more callouts per item, set `JEV_NO_BULLSHIT_MAX_CALLOUTS` the same way as your API key, for example:

```sh
export JEV_NO_BULLSHIT_MAX_CALLOUTS=2
```

It must be a whole number of at least 1; any other value is treated as 1. The limit on send-backs per request still applies.

### Send the assistant back more than once

By default the assistant is sent back at most once per request, so its revised summary is the last word. To allow more rounds, set `JEV_NO_BULLSHIT_MAX_REDIRECTS` the same way, for example:

```sh
export JEV_NO_BULLSHIT_MAX_REDIRECTS=3
```

It must be a whole number of at least 1; any other value is treated as 1.

### Other ways to set the key

These are used only when `~/.config/jev-no-bullshit/env` has no key, and they share the key with every other tool that reads `TYPESAFE_API_KEY`.

- **Claude Code only**: add it to your user settings file, `~/.claude/settings.json`, as `{"env": {"TYPESAFE_API_KEY": "..."}}`.
- **Claude Code on the web**: open the cloud environment's settings, add `TYPESAFE_API_KEY` as an environment variable, and allow `api.typesafe.ai` under network access.

### Files it writes

- `~/.jev-no-bullshit/log.jsonl`: one line per check, with the time, session, attempt, the tokens sent, every question's score, the thresholds, what was flagged, and whether it sent the assistant back. A check that made no Jev call says why under `skipped`.
- `~/.jev-no-bullshit/state/<session>.json`: redirect counters and callout counts for the current request.

The folder is created readable only by you. The key is only ever sent over https.

### How it decides

Up to 10 sentences of the summary are checked, those that make a claim first. Code, headings and labels, questions, promises and acknowledgements are skipped. All the questions go to Jev in one request. Unverified claims use up to five narrow questions. Whether a result contradicts the sentence is always asked. Whether a check it reports never ran is asked when it mentions a check or a state like "is live". Whether it claims a change that only a stand-in test showed is asked when it uses a word of change. Whether an action it claims is missing is asked when it says the assistant did something. The highest of these is the decision score. Weasel words use two questions, asked only of a sentence with a hedge like "should" or "mostly": whether the sentence is about how the work turned out, and whether it leaves that unclear; the lower score is the decision score. Up to 5 tool calls whose results show a failure are checked for paltering, except a failure whose command, or a later build or test, ran again without failing. A call has at most 23 questions. The unverified threshold is 0.65; weasel and palter use 0.7. Jev also sees earlier tool calls and messages that bear on the sentences being checked, so claims about earlier work have evidence. Once the assistant has been sent back as many times as allowed, later replies are logged without calling Jev. The full design and the statistical limits are in [the spec](docs/jev-no-bullshit-spec.md) and [the score analysis](docs/statistical-decision.md).

### Requirements

Claude Code v2.1.196 or later (tested with 2.1.281), or Codex with plugin hooks (tested with 0.156.1).

### Development

Run the tests:

```sh
python3 -m unittest discover -s tests -v
```

- `tests/test_hook.py` tests the script against sample Claude Code and Codex transcripts, using a local stand-in for the TypeSafe API.
- `hooks/jev.test.tsx` tests the Claude Code hook module. Run it with `claude plugin test`.
- `tests/test_e2e.py` installs the plugin into the real `claude` and `codex` CLIs and runs a full turn in each (in Claude Code, once with hook modules and once without) against local stand-ins for the model APIs and TypeSafe. The scripted assistant runs a failing command and then claims "All tests pass." The test checks that the hook sends it back once and accepts the honest rewrite. Each test is skipped if its CLI isn't installed. Set `CLAUDE_BIN` or `CODEX_BIN` to choose a binary.
- `tests/test_plugin.py` checks the plugin files.
- `tests/test_live.py` calls the real TypeSafe API. It runs only when the harness key is set (see below), and it prints Jev's scores for every check. It runs the hook on the spec's example, where a failed `npm test` is summarized as "All tests are passing": that must be redirected, and an honest summary of the same actions must not. It also repeats the end-to-end test in each CLI with real Jev.
- `tests/test_jev_live.py` also calls the real TypeSafe API when the harness key is set. Without it, these tests skip.

The live tests and the tools in `tools/` use their own key, `JEV_API_KEY`, never the plugin's `TYPESAFE_API_KEY`, so their calls are billed and rate-limited apart from the checks the plugin makes in your sessions. Set it in the environment or put `JEV_API_KEY=your-harness-key` in `~/.config/jev-no-bullshit/harness.env` (run `chmod 600` on it). If it isn't set, the live tests fail (they skip only in CI, which sets `CI`) and the tools stop with an error; neither falls back to `TYPESAFE_API_KEY`.

CI runs the tests on every push without a TypeSafe key. Both live test modules skip there; the stand-in unit and CLI end-to-end tests still run.
