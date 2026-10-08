/* SSE-en fra /api/chat. Backend sender fem hendelsestyper:
 * session, tool, reasoning, text, error — og til slutt done. */
import { authFetch } from "@/lib/auth"


export type TurnEvents = {
  onSession?: (id: string) => void
  onTool?: (label: string) => void
  onReasoning?: (text: string) => void
  onText?: (text: string) => void
  onError?: (message: string) => void
  onDone?: (usage: unknown) => void
}

export async function runTurn(
  message: string,
  sessionId: string | null,
  signal: AbortSignal,
  ev: TurnEvents,
) {
  const res = await authFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error("HTTP " + res.status)

  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const frames = buf.split("\n\n")
    buf = frames.pop() ?? ""
    for (const f of frames) {
      const line = f.split("\n").find((l) => l.startsWith("data: "))
      if (!line) continue
      let e: { type: string; [k: string]: unknown }
      try {
        e = JSON.parse(line.slice(6))
      } catch {
        continue
      }
      if (e.type === "session") ev.onSession?.(String(e.session_id))
      else if (e.type === "tool") ev.onTool?.(String(e.label))
      else if (e.type === "reasoning") ev.onReasoning?.(String(e.text))
      else if (e.type === "text") ev.onText?.(String(e.text))
      else if (e.type === "error") ev.onError?.(String(e.message))
      else if (e.type === "done") ev.onDone?.(e.usage)
    }
  }
}
