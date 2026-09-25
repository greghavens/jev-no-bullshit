// pi's half of jev-no-bullshit. When the agent is about to settle, send its
// final reply and the tool calls since the person's last message to the
// Python script, which asks Jev about them. For a flagged reply, append the
// script's feedback as a message and ask pi for one more model request, so
// the model revises in the same run. A clean reply is left alone.
import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"

const SCRIPT = fileURLToPath(new URL("../jev-no-bullshit", import.meta.url))
// The script's feedback starts with this tag.
const TAG = "[jev-no-bullshit]"
const CUSTOM_TYPE = "jev-no-bullshit"
// Redirects per message from the person: JEV_NO_BULLSHIT_MAX_REDIRECTS, a whole number of at least 1, or 1.
function maxRedirects(value: string | undefined): number {
  const n = Number(value)
  return Number.isInteger(n) && n >= 1 ? n : 1
}
const TIMEOUT_MS = 30_000

type Call = { tool: string; input: unknown; result: string | null; error: boolean; now: boolean }

function text(content: unknown): string {
  if (typeof content === "string") return content
  if (!Array.isArray(content)) return ""
  return content
    .map((block) => (block?.type === "text" ? block.text : block?.type === "image" ? "[image]" : ""))
    .filter(Boolean)
    .join("\n")
}

// Run the script with the turn on stdin. Resolves its stdout, or "" on any failure: the check fails open.
function check(turn: object, signal: AbortSignal | undefined): Promise<string> {
  return new Promise((resolve) => {
    let stdout = ""
    const child = spawn("python3", [SCRIPT], { stdio: ["pipe", "pipe", "ignore"], timeout: TIMEOUT_MS, signal })
    child.stdout.on("data", (chunk) => (stdout += chunk))
    child.on("error", () => resolve(""))
    child.on("close", () => resolve(stdout))
    child.stdin.on("error", () => {})
    child.stdin.end(JSON.stringify(turn))
  })
}

export default function (pi: ExtensionAPI) {
  pi.on("agent_before_settle", async (event, ctx) => {
    const { contextMessages: messages, pendingMessages } = event.context
    // Only a finished run, nobody else continuing it, and nothing the person has queued: a message
    // they typed meanwhile has moved on from this reply. (canContinue is false here, since the run
    // ends on the assistant's reply; the feedback message is what lets it continue.)
    if (event.outcome !== "completed" || event.continue || pendingMessages.length) return

    // The task is the person's last message. Feedback goes in as custom messages, so it is not one.
    let taskIndex = -1
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i] as { role: string; content?: unknown }
      if (m.role === "user" && text(m.content).trim() && !text(m.content).trimStart().startsWith(TAG)) {
        taskIndex = i
        break
      }
    }
    const redirects = messages
      .slice(taskIndex + 1)
      .filter((m) => (m as { role: string; customType?: string }).role === "custom" && (m as { customType?: string }).customType === CUSTOM_TYPE).length

    const last = messages[messages.length - 1] as { role: string; content?: unknown; model?: string }
    if (last?.role !== "assistant") return
    const reply = text(last.content).trim()
    if (!reply) return

    const calls: Call[] = []
    const byId = new Map<string, Call>()
    messages.forEach((m, i) => {
      const message = m as { role: string; content?: unknown; toolCallId?: string; isError?: boolean }
      if (message.role === "assistant" && Array.isArray(message.content)) {
        for (const block of message.content) {
          if (block?.type !== "toolCall") continue
          const call = { tool: block.name, input: block.arguments, result: null, error: false, now: i > taskIndex }
          calls.push(call)
          byId.set(block.id, call)
        }
      } else if (message.role === "toolResult") {
        const call = byId.get(message.toolCallId ?? "")
        if (call) {
          call.result = text(message.content)
          call.error = Boolean(message.isError)
        }
      }
    })
    const strip = ({ now: _, ...call }: Call) => call

    const stdout = await check(
      {
        host: "pi",
        session_id: `pi-${ctx.sessionManager.getSessionId()}`,
        task: taskIndex >= 0 ? text((messages[taskIndex] as { content?: unknown }).content) : "",
        actions: calls.filter((c) => c.now).map(strip),
        earlier_actions: calls.filter((c) => !c.now).map(strip),
        // What was said before the reply: a reply that refers to an earlier message rests on it.
        conversation: messages
          .slice(0, -1)
          .map((m) => m as { role: string; content?: unknown })
          .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "custom")
          .map((m) => ({ role: m.role === "custom" ? "hook" : m.role, text: text(m.content) }))
          .filter((m) => m.text.trim()),
        model: last.model,
        last_assistant_message: reply,
        stop_hook_active: redirects > 0,
      },
      ctx.signal,
    )
    let reason = ""
    try {
      const output = stdout.trim() ? JSON.parse(stdout) : {}
      if (output.decision === "block" && typeof output.reason === "string" && output.reason.startsWith(TAG)) reason = output.reason
    } catch {
      return // fail open, as the script does
    }
    // The revision is still checked (and logged); past the limit it is not sent back again.
    if (!reason || redirects >= maxRedirects(process.env.JEV_NO_BULLSHIT_MAX_REDIRECTS)) return
    return {
      entries: [{ type: "custom_message", customType: CUSTOM_TYPE, content: reason, display: true }],
      continue: true,
    }
  })
}
