// opencode's half of jev-no-bullshit. When a session goes idle, send its final
// reply and the tool calls since the person's last message to the Python
// script, which asks Jev about them. For a flagged reply, send the script's
// feedback as a prompt, so the model revises in a turn of its own. A clean
// reply is left alone.
import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import type { Plugin } from "@opencode-ai/plugin"

const SCRIPT = fileURLToPath(new URL("../jev-no-bullshit", import.meta.url))
// The script's feedback starts with this tag, so a prompt that does is ours.
const TAG = "[jev-no-bullshit]"
// Redirects per message from the person: JEV_NO_BULLSHIT_MAX_REDIRECTS, a whole number of at least 1, or 1.
function maxRedirects(value: string | undefined): number {
  const n = Number(value)
  return Number.isInteger(n) && n >= 1 ? n : 1
}
const TIMEOUT_MS = 30_000

type Part = { type: string; text?: string; synthetic?: boolean; tool?: string; callID?: string; state?: any }
type Message = { info: { id: string; role: string; modelID?: string; error?: unknown }; parts: Part[] }
type Call = { tool: string; input: unknown; result: string | null; error: boolean }

function text(parts: Part[]): string {
  return parts
    .filter((p) => p.type === "text" && !p.synthetic && p.text)
    .map((p) => p.text)
    .join("\n")
}

function call(part: Part): Call {
  const state = part.state ?? {}
  let result = state.status === "completed" ? String(state.output ?? "") : state.status === "error" ? String(state.error ?? "") : null
  // The shell tool reports a failed command as completed; its exit code is only in the metadata.
  const exit = state.metadata?.exit
  const failed = typeof exit === "number" && exit !== 0
  if (failed && result !== null) result = `${result.replace(/\n+$/, "")}\nExit code: ${exit}`
  return { tool: part.tool ?? "unknown", input: state.input ?? {}, result, error: state.status === "error" || failed }
}

// Run the script with the turn on stdin. Resolves its stdout, or "" on any failure: the check fails open.
function check(turn: object): Promise<string> {
  return new Promise((resolve) => {
    let stdout = ""
    const child = spawn("python3", [SCRIPT], { stdio: ["pipe", "pipe", "ignore"], timeout: TIMEOUT_MS })
    child.stdout.on("data", (chunk) => (stdout += chunk))
    child.on("error", () => resolve(""))
    child.on("close", () => resolve(stdout))
    child.stdin.on("error", () => {})
    child.stdin.end(JSON.stringify(turn))
  })
}

export const JevNoBullshit: Plugin = async ({ client }) => {
  // The last reply checked in each session, so an idle event repeated for one reply checks it once.
  const checked = new Map<string, string>()

  async function review(sessionID: string) {
    const session = await client.session.get({ path: { id: sessionID } })
    if (!session.data || session.data.parentID) return // subagents report to their parent, which is checked
    const listed = await client.session.messages({ path: { id: sessionID } })
    const messages = (listed.data ?? []) as Message[]

    const last = messages[messages.length - 1]
    if (!last || last.info.role !== "assistant" || last.info.error) return
    if (checked.get(sessionID) === last.info.id) return
    checked.set(sessionID, last.info.id)
    const reply = text(last.parts).trim()
    if (!reply) return

    // The task is the person's last prompt; ours start with the tag.
    let taskIndex = -1
    for (let i = messages.length - 1; i >= 0; i--) {
      const prompt = text(messages[i].parts).trim()
      if (messages[i].info.role === "user" && prompt && !prompt.startsWith(TAG)) {
        taskIndex = i
        break
      }
    }
    const redirects = messages
      .slice(taskIndex + 1)
      .filter((m) => m.info.role === "user" && text(m.parts).trim().startsWith(TAG)).length

    const calls = (from: number, to: number) =>
      messages
        .slice(from, to)
        .filter((m) => m.info.role === "assistant")
        .flatMap((m) => m.parts.filter((p) => p.type === "tool").map(call))

    const stdout = await check({
      host: "opencode",
      session_id: `opencode-${sessionID}`,
      task: taskIndex >= 0 ? text(messages[taskIndex].parts) : "",
      actions: calls(taskIndex + 1, messages.length),
      earlier_actions: calls(0, Math.max(taskIndex, 0)),
      // What was said before the reply: a reply that refers to an earlier message rests on it.
      conversation: messages
        .slice(0, -1)
        .map((m) => ({ role: m.info.role, text: text(m.parts) }))
        .filter((m) => m.text.trim()),
      model: last.info.modelID,
      last_assistant_message: reply,
      stop_hook_active: redirects > 0,
    })
    let reason = ""
    try {
      const output = stdout.trim() ? JSON.parse(stdout) : {}
      if (output.decision === "block" && typeof output.reason === "string" && output.reason.startsWith(TAG)) reason = output.reason
    } catch {
      return // fail open, as the script does
    }
    // The revision is still checked (and logged); past the limit it is not sent back again.
    if (!reason || redirects >= maxRedirects(process.env.JEV_NO_BULLSHIT_MAX_REDIRECTS)) return
    // The person may have typed while Jev was asked; if so, they have moved on from this reply.
    const now = await client.session.messages({ path: { id: sessionID } })
    const latest = (now.data ?? []) as Message[]
    if (latest[latest.length - 1]?.info.id !== last.info.id) return
    await client.session.promptAsync({ path: { id: sessionID }, body: { parts: [{ type: "text", text: reason }] } })
  }

  return {
    event: async ({ event }) => {
      const idle =
        event.type === "session.idle" ||
        (event.type === "session.status" && (event.properties as any).status?.type === "idle")
      if (!idle) return
      try {
        await review((event.properties as { sessionID: string }).sessionID)
      } catch {
        // fail open: a problem with the check never holds up the session
      }
    },
  }
}
