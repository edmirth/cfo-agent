import { createContext, useCallback, useContext, useRef, useState } from "react"
import type { ReactNode } from "react"

import type { Conversation, Message } from "@/lib/conversations"
import { MAX_CONVS, clip, load, newId, save } from "@/lib/conversations"
import { runTurn } from "@/lib/stream"
import { authFetch } from "@/lib/auth"

/* Samtalene ligger i en ref, ikke i state.
 * Et svar strømmer inn token for token; å lage en ny React-state for hver av
 * dem koster mer enn det smaker. Refen er fasit, og en teller tvinger fram
 * ny tegning én gang per animasjonsramme. */
type Ctx = {
  convs: Conversation[]
  /** false når spørsmålet ikke ble tatt imot — tomt, eller samtalen svarer
   *  fortsatt — slik at den som kaller beholder det brukeren skrev. */
  ask: (message: string, shownAs?: string, fresh?: boolean) => boolean
  remove: (id: string) => void
  busy: (id: string | null) => boolean
}

const ConversationsContext = createContext<Ctx | null>(null)

export function useConversations() {
  const c = useContext(ConversationsContext)
  if (!c) throw new Error("useConversations utenfor provider")
  return c
}

export function ConversationsProvider({ children }: { children: ReactNode }) {
  const convs = useRef<Conversation[]>(load())
  const ctrls = useRef(new Map<string, AbortController>())
  const [, setTick] = useState(0)
  const pending = useRef(false)

  const paint = useCallback(() => {
    if (pending.current) return
    pending.current = true
    requestAnimationFrame(() => {
      pending.current = false
      setTick((t) => t + 1)
    })
  }, [])

  const remove = useCallback(
    (id: string) => {
      const c = convs.current.find((x) => x.id === id)
      if (!c || !confirm(`Slette «${c.title}»?`)) return
      ctrls.current.get(id)?.abort()
      ctrls.current.delete(id)
      convs.current = convs.current.filter((x) => x.id !== id)
      save(convs.current)
      if (c.sessionId) {
        authFetch("/api/session/reset?session_id=" + encodeURIComponent(c.sessionId), {
          method: "POST",
        }).catch(() => {})
      }
      if (window.location.hash === "#c/" + id) window.location.hash = ""
      else paint()
    },
    [paint],
  )

  const ask = useCallback(
    (message: string, shownAs?: string, fresh = false): boolean => {
      if (!message.trim()) return false
      const hash = window.location.hash
      const activeId = hash.startsWith("#c/") ? hash.slice(3) : null
      let c = !fresh && activeId ? convs.current.find((x) => x.id === activeId) : undefined
      if (c?.busy) return false

      const now = Date.now()
      if (!c) {
        c = {
          id: newId(),
          title: clip((shownAs || message).trim()),
          sessionId: null,
          created: now,
          updated: now,
          messages: [],
        }
        convs.current.unshift(c)
        if (convs.current.length > MAX_CONVS) convs.current.length = MAX_CONVS
        window.location.hash = "#c/" + c.id
      }
      const conv = c
      const q: Message = { role: "user", text: shownAs || message }
      const m: Message = {
        role: "assistant",
        text: "",
        steps: [],
        done: false,
        started: now,
        open: false,
      }
      conv.messages.push(q, m)
      conv.updated = now
      conv.busy = true
      convs.current = [conv, ...convs.current.filter((x) => x !== conv)]
      save(convs.current)
      paint()

      // Underveis-prat hører hjemme i sporet, ikke i svaret.
      const stash = () => {
        const t = m.text.trim()
        if (t) m.steps!.push({ kind: "note", text: t })
        m.text = ""
      }

      const ctrl = new AbortController()
      ctrls.current.set(conv.id, ctrl)

      runTurn(message, conv.sessionId, ctrl.signal, {
        onSession: (id) => {
          conv.sessionId = id
          save(convs.current)
        },
        onTool: (label) => {
          stash()
          const last = m.steps![m.steps!.length - 1]
          if (last?.kind === "tool" && last.label === label) last.n += 1
          else m.steps!.push({ kind: "tool", label, n: 1 })
          paint()
        },
        onReasoning: (text) => {
          const last = m.steps![m.steps!.length - 1]
          if (last?.kind === "think") last.text += text
          else m.steps!.push({ kind: "think", text })
          paint()
        },
        onText: (text) => {
          m.text += text
          paint()
        },
        onError: (msg) => {
          m.error = msg
          paint()
        },
      })
        .catch((err: Error) => {
          if (err.name !== "AbortError") m.error = "Mistet forbindelsen. Prøv igjen."
        })
        .finally(() => {
          m.done = true
          m.elapsed = Date.now() - m.started!
          // Endte turen på et verktøykall, er siste mellomtekst likevel svaret.
          const last = m.steps![m.steps!.length - 1]
          if (!m.text.trim() && last?.kind === "note") {
            m.text = last.text
            m.steps!.pop()
          }
          conv.busy = false
          conv.updated = Date.now()
          ctrls.current.delete(conv.id)
          save(convs.current)
          paint()
        })
      return true
    },
    [paint],
  )

  const busy = useCallback(
    (id: string | null) => !!(id && convs.current.find((c) => c.id === id)?.busy),
    [],
  )

  return (
    <ConversationsContext.Provider value={{ convs: convs.current, ask, remove, busy }}>
      {children}
    </ConversationsContext.Provider>
  )
}
