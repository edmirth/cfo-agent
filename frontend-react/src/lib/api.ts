/* Alt som hentes fra FastAPI-en. Endepunktene regnes ut uten modell i loopen,
 * så en sidelast koster ingenting — bortsett fra /api/chat, som går via Claude. */

export type Kpi = {
  id: string
  label: string
  plain: string
  unit: string
  better: "low" | "high"
  value: number | null
  target: number
  alert: number
  why: string
  status: "good" | "watch" | "bad" | "unknown"
  headline?: boolean
}

export type Week = {
  index: number
  start: string
  end: string
  label: string
  in: number
  out: number
  expected_in: number
  expected_out: number
  committed_close: number
  expected_close: number
}

export type Cashflow = {
  as_of: string
  opening: number
  weeks: Week[]
  low_committed: { label: string; start: string; amount: number }
  low_expected: { label: string; start: string; amount: number }
  goes_negative: { label: string; start: string } | null
  goes_negative_committed: { label: string; start: string } | null
  open_invoices: { receivable: number; receivable_total: number }
  // Mixed by design: the figures are numbers, the stated-or-assumed notes are
  // prose, and feriepenger_maned_oppgitt is a flag.
  assumptions: { monthly_wages: number; [k: string]: number | string | boolean }
  warnings: string[]
  error?: string
}

export type Commitments = {
  bank: number
  restricted: number
  items: { id: string; label: string; amount: number; kind: string; due: string }[]
  free_now: number
  free_all: number
  verdict: string
  error?: string
}

/** Én måned i saldobalansen. Null betyr «rapporten dekker ikke måneden», ikke null kroner. */
export type Month = {
  month: string
  revenue: number | null
  wages: number | null
  result: number | null
  bank: number | null
}

export type Overview = {
  company: string
  kpis: Record<string, number>
  monthly?: Month[]
  top_debtor?: { name: string; amount: number; share_pct: number }
  flags?: { ubokfort_skatt?: number }
  generated_at?: string
  error?: string
}

/** Forsidens oppsummering. `stale` er gårsdagens tekst, når dagens ikke lot seg skrive. */
export type Summary = {
  verdict?: string | null
  text?: string
  written?: string
  stale?: boolean
  error?: string
}

export type Preflight = {
  condition: string
  checks: { id: string; label: string; status: string; headline: string; detail?: string }[]
  error?: string
}

export type Dashboard = { industry?: string; kpis: Kpi[]; error?: string }

export type Preset = { id: string; label: string }

/** Kaster på feil, slik at hver del av forsiden kan feile for seg. */
export async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  const data = await res.json()
  if (data && typeof data === "object" && "error" in data && data.error) {
    throw new Error(String(data.error))
  }
  return data as T
}

export const api = {
  health: () => get<{ company: string; model: string }>("/api/health"),
  overview: () => get<Overview>("/api/overview"),
  dashboard: () => get<Dashboard>("/api/dashboard"),
  commitments: () => get<Commitments>("/api/commitments"),
  preflight: () => get<Preflight>("/api/preflight"),
  cashflow: () => get<Cashflow>("/api/cashflow"),
  summary: () => get<Summary>("/api/summary"),
  presets: () => get<{ presets: Preset[] }>("/api/presets"),
}
