/* En sak fra mandagsbrevet, åpnet med lenken i e-posten, uten innlogging
 * (kort 11). Lenken er nøkkelen til denne ene saken: den viser saken og lar
 * daglig leder velge, én gang, i en uke. Alt annet i appen krever innlogging,
 * og det er dit siden peker når lenken ikke virker lenger.
 *
 * Saken tegnes med den samme DecisionBody som i appen, så den ser lik ut og
 * valget sendes med det samme utkastet. */
import { useEffect, useState } from "react"

import { Wordmark } from "@/components/brand"
import { DecisionBody, type DeckCard, type DeckState } from "@/components/decision"
import { useTheme } from "@/hooks/use-theme"

async function post<T>(path: string, body: object): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    throw new Error(
      typeof data?.detail === "string" ? data.detail : "Fikk ikke kontakt med serveren.",
    )
  }
  return data as T
}

type View =
  | { kind: "loading" }
  | { kind: "refused"; msg: string }
  | { kind: "card"; card: DeckCard }
  | { kind: "decided"; card: DeckCard; label: string }

export function Godkjenn({ token }: { token: string }) {
  useTheme()
  const [view, setView] = useState<View>({ kind: "loading" })
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [draft, setDraft] = useState<string | null>(null)

  useEffect(() => {
    post<{ card: DeckCard }>("/api/link", { token })
      .then((d) => setView({ kind: "card", card: d.card }))
      .catch((e: Error) => setView({ kind: "refused", msg: e.message }))
  }, [token])

  const card = view.kind === "card" || view.kind === "decided" ? view.card : null
  const draftOf = (c: DeckCard) => draft ?? c.draft?.text ?? ""

  const decide = async (_cardId: string, option: string) => {
    if (!card) return
    setBusy(true)
    setFailed(null)
    try {
      const d = await post<{ card: DeckCard & { decided?: { label?: string } } }>(
        "/api/link/decide",
        { token, option, ...(card.draft ? { draft_text: draftOf(card) } : {}) },
      )
      setView({ kind: "decided", card, label: d.card.decided?.label ?? "" })
    } catch (e) {
      setFailed((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // Det DecisionBody trenger av sakene i appen, for denne ene saken.
  const state = {
    deck: null,
    load: async () => {},
    decide,
    busy: busy && card ? card.id : null,
    failed: failed && card ? { id: card.id, msg: failed } : null,
    draftOf,
    setDraft: (_id: string, text: string) => setDraft(text),
  } as DeckState

  // Videre inn i appen, med mandagsbrevets merke (?fra=brev&b=…) i behold, så
  // trykket telles for den som har sagt ja. Innlogging kreves der.
  const toApp = card ? `#saker/${card.id}` : "#saker"

  return (
    <div className="min-h-svh">
      <header className="border-border flex h-14 items-center border-b px-5 sm:px-8">
        <Wordmark className="text-[22px]" />
      </header>
      <main className="mx-auto w-full max-w-3xl px-5 pt-8 pb-24 sm:px-8">
        {view.kind === "loading" ? null : view.kind === "refused" ? (
          <div className="grid gap-5">
            <h1 className="font-heading text-[32px] leading-[1.1] tracking-[-0.02em]">
              Lenken virker ikke.
            </h1>
            <p className="text-[15px] leading-6" role="alert">
              {view.msg}
            </p>
            <a href="#saker" className="text-good-text text-[15px] font-medium hover:underline">
              Logg inn og se sakene →
            </a>
          </div>
        ) : view.kind === "decided" ? (
          <div className="grid gap-5">
            <h1 className="font-heading text-[32px] leading-[1.1] tracking-[-0.02em]">
              Registrert.
            </h1>
            <p className="text-[15px] leading-6">
              «{view.label}» — {view.card.title}
            </p>
            <p className="text-muted-foreground text-[13px] leading-5">
              Valget er lagret som om du hadde trykket i appen. Lenken er brukt og virker ikke
              igjen.
            </p>
            <a href={toApp} className="text-good-text text-[15px] font-medium hover:underline">
              Åpne saken i appen →
            </a>
          </div>
        ) : (
          <div className="grid gap-8">
            <p className="label">Fra mandagsbrevet</p>
            <DecisionBody c={view.card} state={state} />
            <a href={toApp} className="text-muted-foreground text-[13px] hover:underline">
              Åpne saken i appen (krever innlogging)
            </a>
          </div>
        )}
      </main>
    </div>
  )
}
