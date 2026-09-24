import { expect, test } from "claude-code/testing"

const REPLY = "I ran the tests and all 56 passed."
const FEEDBACK = "[jev-no-bullshit] Double-check these before you finish: ..."

// Stands in for the engine: runs the checker script by handing out the next
// verdict, and records what the plugin submits, the environment each check
// ran with, and the order of checks and Stop hooks.
function engine(on: any, verdicts: (string | undefined)[], opts: { stopBlocks?: string; env?: Record<string, string> } = {}) {
  const submitted: { text: string; context?: string[] }[] = []
  const envs: Record<string, string>[] = []
  const order: string[] = []
  on("process.run", (_$: any, e: any) => {
    order.push("check")
    envs.push(e.init?.env ?? {})
    const reason = verdicts.shift()
    return { value: { exitCode: 0, stderr: "", stdout: reason ? JSON.stringify({ decision: "block", reason }) : "" } }
  })
  on("ui.log", () => ({ value: undefined }))
  on("env.get", (_$: any, e: any) => ({ value: opts.env?.[e.name] }))
  on("prompt.submit", (_$: any, e: any) => {
    if (e.text.startsWith("[jev-no-bullshit]")) submitted.push({ text: e.text, context: e.context })
    return { text: e.text }
  })
  // The plain Stop hooks beneath the module, hooks/hooks.json's among them.
  on("classic.Stop", () => {
    order.push("stop hooks")
    return opts.stopBlocks ? { block: opts.stopBlocks } : {}
  })
  on("turn.complete", (_$: any, e: any) => ({ text: e.answer }))
  return { submitted, envs, order }
}

// The end of a turn, as the engine raises it after the Stop hooks. The
// plugin's submit is not awaited (it resolves only as the next turn starts),
// so give it a moment to arrive.
async function endTurn($: any, answer: string, turnId = "t") {
  await $.turn.complete({ answer, durationMs: 1, isAborted: false, turnId, reason: "answer" })
  await new Promise((resolve) => setTimeout(resolve, 20))
}

async function stop($: any, message: string) {
  return $.classic.Stop({ stop_hook_active: false, last_assistant_message: message })
}

test("a clean reply sends nothing", async ($, on) => {
  const { submitted } = engine(on, [undefined])
  expect((await stop($, REPLY)).block).toBeUndefined()
  await endTurn($, REPLY)
  expect(submitted).toEqual([])
})

test("a flagged reply's feedback is sent as the prompt's own text, not a Stop block", async ($, on) => {
  const { submitted } = engine(on, [FEEDBACK])
  expect((await stop($, REPLY)).block).toBeUndefined()
  expect(submitted).toEqual([])
  await endTurn($, REPLY)
  expect(submitted.map((s) => s.text)).toEqual([FEEDBACK])
  expect(submitted[0].context).toBeUndefined()
  await endTurn($, "a later turn")
  expect(submitted.length).toBe(1)
})

test("the check runs before the plain Stop hooks, so the one in hooks/hooks.json can stand down", async ($, on) => {
  const { order } = engine(on, [undefined])
  await stop($, REPLY)
  expect(order).toEqual(["check", "stop hooks"])
})

test("no redirect when another Stop hook already sent the model back", async ($, on) => {
  const { submitted } = engine(on, [FEEDBACK], { stopBlocks: "another hook's reason" })
  expect((await stop($, REPLY)).block).toBe("another hook's reason")
  await endTurn($, REPLY)
  expect(submitted).toEqual([])
})

test("no redirect for a turn the person typed a prompt over", async ($, on) => {
  const { submitted } = engine(on, [FEEDBACK, FEEDBACK])
  await $.prompt.submit({ text: "and one more thing", turnId: "busy" } as any)
  await stop($, REPLY)
  await endTurn($, REPLY, "busy")
  expect(submitted).toEqual([])
  // Their prompt's own turn is checked and redirected as usual.
  await stop($, "Answer to one more thing.")
  await endTurn($, "Answer to one more thing.", "next")
  expect(submitted.map((s) => s.text)).toEqual([FEEDBACK])
})

test("the checker is told which turns are redirects, by environment", async ($, on) => {
  const { envs } = engine(on, [FEEDBACK, undefined, undefined])
  await stop($, REPLY)
  await endTurn($, REPLY)
  await stop($, "Revised reply.")
  await $.prompt.submit({ text: "next task" })
  await stop($, "Another reply.")
  expect(envs.map((env) => env.JEV_NO_BULLSHIT_REDIRECT)).toEqual(["0", "1", "0"])
  expect(envs.every((env) => env.JEV_NO_BULLSHIT_MODULE === "1")).toBe(true)
})

test("at most 1 redirect per prompt by default, and every reply is still checked so the plain Stop hook stands down", async ($, on) => {
  const { submitted, envs, order } = engine(on, Array(10).fill(FEEDBACK))
  for (let i = 0; i < 4; i++) {
    await stop($, `reply ${i}`)
    await endTurn($, `reply ${i}`)
  }
  expect(submitted.length).toBe(1)
  expect(envs.length).toBe(4)
  expect(order.filter((o) => o === "check").length).toBe(4)
})

test("JEV_NO_BULLSHIT_MAX_REDIRECTS raises the limit", async ($, on) => {
  const { submitted } = engine(on, Array(10).fill(FEEDBACK), { env: { JEV_NO_BULLSHIT_MAX_REDIRECTS: "3" } })
  for (let i = 0; i < 6; i++) {
    await stop($, `reply ${i}`)
    await endTurn($, `reply ${i}`)
  }
  expect(submitted.length).toBe(3)
})
