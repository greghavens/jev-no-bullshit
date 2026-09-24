// Claude Code's half of jev-no-bullshit, as function hooks. Codex runs the
// Python script as a plain Stop hook (hooks/hooks.json); here this module
// runs it instead, so that it decides what the person sees.
//
// The reply streams to the person as it is written. When the turn ends, the
// script asks Jev about it. A clean reply is left alone. A flagged one is
// redrawn as a single dim line, and the model is sent back with a short prompt
// of this plugin's own that carries the script's feedback as context the
// model reads and the person does not. A Stop block would not do: the engine
// draws its "Stop hook error" row where no plugin can redraw it. The model's
// revision is what the person reads.
import type { Register } from "claude-code"

const withdrawn = { plugin: "jev-no-bullshit", key: "withdrawn" } as const
const redirects = { plugin: "jev-no-bullshit", key: "redirects" } as const
const pending = { plugin: "jev-no-bullshit", key: "pending" } as const
const sent = { plugin: "jev-no-bullshit", key: "sent" } as const

// What the person sees of a redirect; the feedback itself rides as context.
export const NOTICE = "Jev flagged the last reply. Revise it using the attached notes."
// How many withdrawn replies to remember; older ones draw normally again.
const KEEP = 20
// Redirects per prompt from the person, whatever the script says.
const MAX_REDIRECTS = 3

function same(a: string, b: string): boolean {
  return a.trim().length > 0 && a.trim() === b.trim()
}

export const register: Register = (on) => {
  // Our own prompt gets the feedback attached; one the person sends starts a
  // fresh check, redirect count included.
  on("prompt.submit", async ($, e, next) => {
    const { value: feedback = "" } = await $.state.get(sent)
    await $.state.set(sent, "")
    if (feedback && e.text === NOTICE) return next({ ...e, context: [...(e.context ?? []), feedback] })
    await $.state.set(redirects, 0)
    return next(e)
  })

  on("classic.Stop", async ($, e, next) => {
    // Check before next(): the plain Stop hook in hooks/hooks.json runs inside it, and stands down
    // for a reply this run has marked as checked. Where modules do not load, it checks instead.
    const { value: count = 0 } = await $.state.get(redirects)
    let feedback = ""
    if (count < MAX_REDIRECTS) {
      try {
        const run = await $.process.run(["python3", `${$.plugin.root}/jev-no-bullshit`], {
          stdin: JSON.stringify(e),
          // The redirect mark stands in for stop_hook_active, which a prompt of ours does not
          // set, so the script's counters and cap carry over.
          env: { JEV_NO_BULLSHIT_MODULE: "1", JEV_NO_BULLSHIT_REDIRECT: count > 0 ? "1" : "0" },
          timeoutMs: 30_000,
        })
        const output = run.stdout.trim() ? JSON.parse(run.stdout) : {}
        if (output.decision === "block" && typeof output.reason === "string") feedback = output.reason
      } catch (error) {
        $.ui.log(`jev-no-bullshit: check skipped: ${error}`) // fail open, as the script does
      }
    }
    const result = await next(e)
    // Another Stop hook sent the model back already; one redirect at a time.
    if (!feedback || result.block) return result
    const reply = e.last_assistant_message ?? ""
    if (reply) {
      const { value = [], version } = await $.state.get(withdrawn)
      await $.state.set(withdrawn, [...value, reply].slice(-KEEP), { ifVersion: version })
    }
    await $.state.set(redirects, count + 1)
    await $.state.set(pending, feedback)
    return result
  })

  // A Stop hook may not submit (the turn is still its own), so the redirect
  // waits for the turn to end.
  on("turn.complete", async ($, e, next) => {
    const result = await next(e)
    if (e.agentId) return result
    const { value: feedback } = await $.state.get(pending)
    if (feedback) {
      await $.state.set(pending, "")
      await $.state.set(sent, feedback)
      void $.prompt.submit({ text: NOTICE })
    }
    return result
  })

  on("ui.render", { component: "AssistantMessage" }, async ($, e, next) => {
    const { value = [] } = await $.state.get(withdrawn)
    if (!value.some((reply) => same(reply, e.props.text))) return next(e)
    const { Text } = $.ui.resolve(e)
    return <Text dimColor>Reply withdrawn after the Jev check; the revised reply follows.</Text>
  })
}
