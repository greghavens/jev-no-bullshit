// Claude Code's half of jev-no-bullshit, as function hooks. Codex runs the
// Python script as a plain Stop hook (hooks/hooks.json); here this module
// runs it instead, so that no Stop block is needed.
//
// The reply streams to the person as it is written and stays on screen. When
// the turn ends, the script asks Jev about it. A clean reply is left alone.
// For a flagged one, the module submits the script's feedback as a prompt of
// its own, so the model revises and the person sees exactly what was flagged.
// A Stop block would not do: the engine draws its "Stop hook error" row where
// no plugin can redraw it.
import type { Register } from "claude-code"

const redirects = { plugin: "jev-no-bullshit", key: "redirects" } as const
const pending = { plugin: "jev-no-bullshit", key: "pending" } as const
const superseded = { plugin: "jev-no-bullshit", key: "superseded" } as const

// Redirects per prompt from the person: JEV_NO_BULLSHIT_MAX_REDIRECTS, a whole number of at least 1, or 1.
function maxRedirects(value: string | undefined): number {
  const n = Number(value)
  return Number.isInteger(n) && n >= 1 ? n : 1
}
// The script's feedback starts with this tag, so a prompt that does is ours.
const TAG = "[jev-no-bullshit]"

export const register: Register = (on) => {
  // A prompt from anyone else starts a fresh count. One typed while a turn runs
  // means the person has moved on: that turn's feedback is dropped, not sent
  // after their prompt about a reply they have already answered.
  on("prompt.submit", async ($, e, next) => {
    if (e.text.startsWith(TAG)) return next(e)
    await $.state.set(redirects, 0)
    if (e.turnId) await $.state.set(superseded, e.turnId)
    return next(e)
  })

  on("classic.Stop", async ($, e, next) => {
    // Check before next(): the plain Stop hook in hooks/hooks.json runs inside it, and stands down
    // for a reply this run has marked as checked. Where modules do not load, it checks instead.
    // The script runs on every reply, capped or not, so that mark is always written; the script
    // enforces its own cap on redirects.
    const { value: count = 0 } = await $.state.get(redirects)
    let feedback = ""
    try {
      const run = await $.process.run(["python3", `${$.plugin.root}/jev-no-bullshit`], {
        stdin: JSON.stringify(e),
        // The redirect mark stands in for stop_hook_active, which a prompt of ours does not
        // set, so the script's counters and cap carry over.
        env: { JEV_NO_BULLSHIT_MODULE: "1", JEV_NO_BULLSHIT_REDIRECT: count > 0 ? "1" : "0" },
        timeoutMs: 30_000,
      })
      const output = run.stdout.trim() ? JSON.parse(run.stdout) : {}
      if (output.decision === "block" && typeof output.reason === "string" && output.reason.startsWith(TAG)) feedback = output.reason
    } catch (error) {
      $.ui.log(`jev-no-bullshit: check skipped: ${error}`) // fail open, as the script does
    }
    const result = await next(e)
    // Another Stop hook sent the model back already; one redirect at a time.
    await $.state.set(pending, feedback && !result.block ? feedback : "")
    return result
  })

  // A Stop hook may not submit (the turn is still its own), so the redirect
  // waits for the turn to end. The feedback is the prompt's text, not context
  // a hook attaches: the engine may deliver a plugin's own prompt without
  // running that plugin's prompt.submit hook, and the text always arrives.
  on("turn.complete", async ($, e, next) => {
    const result = await next(e)
    if (e.agentId) return result
    const { value: feedback = "" } = await $.state.get(pending)
    if (!feedback) return result
    await $.state.set(pending, "")
    const { value: typedOver = "" } = await $.state.get(superseded)
    const { value: count = 0 } = await $.state.get(redirects)
    if (typedOver === e.turnId || count >= maxRedirects(await $.env.get("JEV_NO_BULLSHIT_MAX_REDIRECTS"))) return result
    await $.state.set(redirects, count + 1)
    void $.prompt.submit({ text: feedback })
    return result
  })
}
