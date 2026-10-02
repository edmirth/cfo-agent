/* Rekkefølgen på det som krever handling.
 *
 * Alvorsgraden bestemmer. Penger og tid skiller bare saker som er like
 * alvorlige, og summen av dem er klemt under båndbredden, så en advarsel kan
 * ikke klatre forbi noe kritisk uansett hvor stort beløpet er. Det er med
 * vilje: en daglig leder som får det dyreste først, og ikke det farligste,
 * rydder feil sak. */

export type Signal = {
  id: string
  sev: "crit" | "warn" | "note"
  tag: string
  title: string
  body: string
  ask: string
  /** Kroner på spill. Står som tall på kortet, og skiller like alvorlige saker. */
  amount?: number
  /** Når det slår inn. Det som haster først, kommer først. */
  due?: string
  /** Liten justering innenfor samme alvorsgrad, aldri nok til å bytte band. */
  nudge?: number
}

const BASE = { crit: 1000, warn: 500, note: 100 }
export const DAY = 86_400_000

export function score(s: Signal, now: number): number {
  const money = s.amount ? Math.min(250, Math.abs(s.amount) / 10_000) : 0
  const days = s.due ? (new Date(s.due).getTime() - now) / DAY : null
  const soon = days == null ? 0 : Math.max(0, 200 - Math.max(0, days) * 4)
  // Klemt under båndbredden, så invarianten holder uansett hva vi finner på å
  // legge til senere.
  return BASE[s.sev] + Math.min(499, money + soon + (s.nudge || 0))
}

export const rank = (list: Signal[], now = Date.now()): Signal[] =>
  [...list].sort((a, b) => score(b, now) - score(a, now))

/** Det som skal stå stort: alt kritisk, ellers de to øverste. */
export function split(ranked: Signal[]): [Signal[], Signal[]] {
  const crit = ranked.filter((s) => s.sev === "crit").slice(0, 3)
  const lead = crit.length ? crit : ranked.slice(0, 2)
  return [lead, ranked.filter((s) => !lead.includes(s))]
}

/** «om 12 dager» sier mer enn en dato når fristen er nær. */
export function dueIn(iso: string | undefined, now = Date.now()): string | null {
  if (!iso) return null
  const days = Math.round((new Date(iso).getTime() - now) / DAY)
  if (Number.isNaN(days)) return null
  if (days < 0) return "forfalt"
  if (days === 0) return "i dag"
  if (days === 1) return "i morgen"
  if (days <= 60) return `om ${days} dager`
  return null
}
