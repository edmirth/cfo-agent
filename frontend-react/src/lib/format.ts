/* Tall og datoer på norsk. Portert fra den gamle frontenden, uendret oppførsel:
 * mellomrom som tusenskille, komma som desimaltegn, og enheten backend oppgir. */

export const kr = (n: number | null | undefined) =>
  n == null ? "–" : Math.round(n).toLocaleString("nb-NO").replace(/ /g, " ")

export const mill = (n: number | null | undefined) => {
  if (n == null) return "–"
  const a = Math.abs(n)
  if (a >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " mill."
  if (a >= 1e4) return Math.round(n / 1e3) + " 000"
  return kr(n)
}

export const pct = (n: number | null | undefined, d = 1) =>
  n == null ? "–" : n.toFixed(d).replace(".", ",") + " %"

/** Backend oppgir enheten selv: %, kr, dager eller x. */
export const unit = (v: number | null | undefined, u: string, d = 1) => {
  if (v == null) return "–"
  if (u === "%") return pct(v, d)
  if (u === "kr") return kr(v) + " kr"
  if (u === "dager") return Math.round(v) + " dager"
  if (u === "x") return v.toFixed(1).replace(".", ",")
  return kr(v) + (u ? " " + u : "")
}

const DAYS = ["søndag", "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag"]

export const dateNo = (iso: string) =>
  new Date(iso).toLocaleDateString("nb-NO", { day: "numeric", month: "long" })

export const dayNo = (iso: string) => DAYS[new Date(iso).getDay()]

/** Setningen skal ende på punktum, men aldri to. */
export const stop = (t: string) => t + (/[.!?]$/.test(t.trim()) ? "" : ".")
