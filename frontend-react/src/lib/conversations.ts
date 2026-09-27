/* Samtalene lagres i nettleseren, én session_id per samtale.
 * Backend holder historikken i minnet, så lista og det som ble sagt må ligge
 * her for at en samtale skal kunne åpnes igjen. Portert fra app.js. */

export type Step =
  | { kind: "tool"; label: string; n: number }
  | { kind: "note" | "think"; text: string }

export type Message = {
  role: "user" | "assistant"
  text: string
  steps?: Step[]
  done?: boolean
  error?: string
  started?: number
  elapsed?: number
  open?: boolean
}

export type Conversation = {
  id: string
  title: string
  sessionId: string | null
  created: number
  updated: number
  messages: Message[]
  busy?: boolean
}

const STORE = "cfo.conversations.v1"
export const MAX_CONVS = 60

export function load(): Conversation[] {
  try {
    const v = JSON.parse(localStorage.getItem(STORE) || "[]")
    if (!Array.isArray(v)) return []
    for (const c of v as Conversation[]) {
      for (const m of c.messages || []) {
        if (m.role !== "assistant") continue
        if (!m.steps) m.steps = []
        // Et svar som var underveis da siden ble lukket, blir aldri ferdig.
        if (!m.done) {
          m.done = true
          m.error = m.error || "Svaret ble avbrutt før det var ferdig."
        }
      }
    }
    return v as Conversation[]
  } catch {
    return []
  }
}

export function save(convs: Conversation[]) {
  try {
    localStorage.setItem(
      STORE,
      JSON.stringify(convs.slice(0, MAX_CONVS), (k, v) => (k === "busy" ? undefined : v)),
    )
  } catch {
    /* privat modus eller full lagring: samtalen virker likevel */
  }
}

export const newId = () =>
  (crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2))
    .replace(/-/g, "")

export const clip = (t: string, n = 64) =>
  t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t

export function bucket(ts: number) {
  const d = new Date(ts)
  const now = new Date()
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((day(now) - day(d)) / 864e5)
  if (diff <= 0) return "I dag"
  if (diff === 1) return "I går"
  if (diff < 7) return "Siste 7 dager"
  if (diff < 30) return "Siste 30 dager"
  return "Eldre"
}
