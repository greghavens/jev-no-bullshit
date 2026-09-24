import { expect, test } from "claude-code/testing"
import { NOTICE } from "./jev"

const REPLY = "I ran the tests and all 56 passed."
const FEEDBACK = "[jev-no-bullshit] Double-check these before you finish: ..."

// Stands in for the engine: runs the checker script by handing out the next
// verdict, draws a row's text as written, and records what the plugin submits,
// the environment each check ran with, and the order of checks and Stop hooks.
function engine(on: any, verdicts: (string | undefined)[], opts: { stopBlocks?: string } = {}) {
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
  on("ui.render", ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text>{e.props.text}</Text>
  })
  on("prompt.submit", (_$: any, e: any) => {
    submitted.push({ text: e.text, context: e.context })
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
async function endTurn($: any, answer: string) {
  await $.turn.complete({ answer, durationMs: 1, isAborted: false, turnId: "t", reason: "answer" })
  await new Promise((resolve) => setTimeout(resolve, 20))
}

async function stop($: any, message: string) {
  return $.classic.Stop({ stop_hook_active: false, last_assistant_message: message })
}

async function draw($: any, surface: "terminal" | "desktop", text: string) {
  return $.ui.mount({ plugin: "jev-no-bullshit", surface, component: "AssistantMessage", props: { text, isFirstOfReply: true } })
}

test("a clean reply draws as written and nothing is sent", async ($, on) => {
  const { submitted } = engine(on, [undefined])
  expect((await stop($, REPLY)).block).toBeUndefined()
  await endTurn($, REPLY)
  expect(submitted).toEqual([])
  for (const surface of ["terminal", "desktop"] as const) {
    const ui = await draw($, surface, REPLY)
    expect(await ui.find({ text: REPLY })).toBeDefined()
    await ui.unmount()
  }
})

test("a flagged reply is withdrawn and the feedback goes as hidden context, not a Stop block", async ($, on) => {
  const { submitted } = engine(on, [FEEDBACK])
  expect((await stop($, REPLY)).block).toBeUndefined()
  expect(submitted).toEqual([])
  await endTurn($, REPLY)
  expect(submitted).toEqual([{ text: NOTICE, context: [FEEDBACK] }])
  await endTurn($, "a later turn")
  expect(submitted.length).toBe(1)
  for (const surface of ["terminal", "desktop"] as const) {
    const ui = await draw($, surface, REPLY)
    expect(await ui.find({ text: /Reply withdrawn/ })).toBeDefined()
    expect(await ui.find({ text: REPLY })).toBeUndefined()
    await ui.unmount()
    const other = await draw($, surface, "Here is the revised reply.")
    expect(await other.find({ text: /withdrawn/ })).toBeUndefined()
    await other.unmount()
  }
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
  const ui = await draw($, "terminal", REPLY)
  expect(await ui.find({ text: REPLY })).toBeDefined()
  await ui.unmount()
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

test("at most 3 redirects per prompt, even if the checker keeps flagging", async ($, on) => {
  const { submitted, envs } = engine(on, Array(10).fill(FEEDBACK))
  for (let i = 0; i < 6; i++) {
    await stop($, `reply ${i}`)
    await endTurn($, `reply ${i}`)
  }
  expect(submitted.length).toBe(3)
  expect(envs.length).toBe(3) // no check once the cap is reached
})
