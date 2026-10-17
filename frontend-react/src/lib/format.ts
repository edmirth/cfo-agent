/* Tall og datoer på norsk. Portert fra den gamle frontenden, uendret oppførsel:
 * mellomrom som tusenskille, komma som desimaltegn, og enheten backend oppgir. */

export const kr = (n: number | null | undefined) => {
  if (n == null) return "–"
  // Math.round(-0.4) is -0, and that prints as «-0». Nobody owes minus nothing.
  const v = Math.round(n) || 0
  return v.toLocaleString("nb-NO").replace(/ /g, " ")
}

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

/** «6. okt» — «6. oktober» is too wide to put on thirteen rows. */
export const dateShortNo = (iso: string) =>
  new Date(iso).toLocaleDateString("nb-NO", { day: "numeric", month: "short" })

export const dayNo = (iso: string) => DAYS[new Date(iso).getDay()]

/** Setningen skal ende på punktum, men aldri to. */
export const stop = (t: string) => t + (/[.!?]$/.test(t.trim()) ? "" : ".")

/** «1,6 MNOK» for store beløp, ellers kroner med tusenskille. */
export const mnok = (n: number | null | undefined) => {
  if (n == null) return "–"
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " MNOK"
  return kr(n) + " kr"
}

const ISO = /\b(\d{4})-(\d{2})-(\d{2})\b/g

/** ISO-datoer midt i en setning blir «24. juli», med år bare når det ikke er i år. */
export const datesNo = (t: string) =>
  t.replace(ISO, (_, y: string, m: string, d: string) => {
    const at = new Date(Number(y), Number(m) - 1, Number(d))
    const thisYear = at.getFullYear() === new Date().getFullYear()
    return at.toLocaleDateString("nb-NO", {
      day: "numeric",
      month: "long",
      ...(thisYear ? {} : { year: "numeric" }),
    })
  })

/** Et faktum på en sak, slik backend sender det («bank kr», «3140405.87»),
 *  gjort lesbart: «Bank», «3 140 406 kr». Ukjente former står som de er. */
export function fact(label: string, value: string): { label: string; value: string } {
  let l = label.trim().replace(/\bforste\b/g, "første")
  const money = /\s+kr$/i.test(l)
  if (money) l = l.replace(/\s+kr$/i, "")
  l = l.charAt(0).toUpperCase() + l.slice(1)
  const v = value.trim()
  if (/^-?\d+(\.\d+)?$/.test(v)) {
    return { label: l, value: kr(Number(v)) + (money ? " kr" : "") }
  }
  return { label: l, value: datesNo(v) }
}
