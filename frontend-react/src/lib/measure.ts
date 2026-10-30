/* Måling av bruken (kort 37), bare med brukerens ja: tid i appen og trykk fra
 * mandagsbrevet. Serveren lagrer ingenting uten et ja uansett hva appen sender;
 * dette er bare det appen trenger for å spørre og for å melde fra om et trykk. */
import { authFetch } from "@/lib/auth"

/** Ja, nei, eller ikke spurt ennå (null). */
export async function getConsent(): Promise<boolean | null> {
  const res = await authFetch("/api/consent")
  if (!res.ok) throw new Error(`/api/consent: HTTP ${res.status}`)
  return (await res.json()).measure
}

export async function setConsent(measure: boolean): Promise<void> {
  const res = await authFetch("/api/consent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ measure }),
  })
  if (!res.ok) throw new Error(`/api/consent: HTTP ${res.status}`)
}

export type Tap = { brief: number; link: "brief" | "card" | "saker"; card: string | null }

/** Lenkene i mandagsbrevet har ?fra=brev&b=<brevet> foran #…. Leser merket,
 * tar det ut av adressen så det ikke telles igjen ved en oppdatering, og sier
 * hva som ble trykket: brevet, en sak eller Saker. */
export function takeTap(): Tap | null {
  const params = new URLSearchParams(window.location.search)
  if (params.get("fra") !== "brev") return null
  const brief = Number(params.get("b"))
  params.delete("fra")
  params.delete("b")
  const rest = params.toString()
  window.history.replaceState(
    null,
    "",
    window.location.pathname + (rest ? `?${rest}` : "") + window.location.hash,
  )
  if (!Number.isInteger(brief) || brief <= 0) return null
  const hash = window.location.hash
  if (hash.startsWith("#saker/")) return { brief, link: "card", card: hash.slice(7) || null }
  if (hash === "#saker") return { brief, link: "saker", card: null }
  return { brief, link: "brief", card: null }
}

export function sendTap(tap: Tap): void {
  authFetch("/api/email-tap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(tap),
  }).catch(() => {})
}
