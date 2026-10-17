/* Arvaka sine byggeklosser: ordmerket, statusprikken og overskriftene som
 * hver side bruker. Porteføljen v1.0 er kilden; det som står her er reglene
 * derfra i kodeform, så sidene ikke trenger å huske dem hver for seg. */
import type { ReactNode } from "react"

/** Ordmerket med prikken framover. Under 80 px bredt brukes monogrammet. */
export function Wordmark({ className = "text-[22px]" }: { className?: string }) {
  return (
    <span className={`arv-wordmark ${className}`} aria-label="Arvaka">
      Arvaka
      <i aria-hidden />
    </span>
  )
}

/** «A» på grønt: app-ikon, favicon og avatar. */
export function Monogram({ className = "size-8 text-[22px]" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`bg-brand-900 text-[var(--ivory)] inline-flex shrink-0 items-center justify-center rounded-md font-heading leading-none ${className}`}
    >
      <span className="translate-y-[0.04em]">A</span>
    </span>
  )
}

export type Light = "green" | "yellow" | "red"

const LIGHT: Record<Light, { word: string; dot: string; text: string }> = {
  green: { word: "Grønn", dot: "bg-positive", text: "text-good-text" },
  yellow: { word: "Gul", dot: "bg-warning", text: "text-foreground" },
  red: { word: "Rød", dot: "bg-negative", text: "text-bad-text" },
}

/** Prikken og ordet. Fargen står aldri alene: ordet sier det samme. */
export function Status({ light, className = "" }: { light: Light; className?: string }) {
  const l = LIGHT[light]
  return (
    <span
      className={`${l.text} inline-flex items-center gap-2 text-xs font-medium tracking-[0.04em] uppercase ${className}`}
    >
      <span aria-hidden className={`size-2 rounded-full ${l.dot}`} />
      {l.word}
    </span>
  )
}

/** Hastegrad som prikk: rødt bare når det faktisk haster. */
export function Dot({ tone }: { tone: "bad" | "warn" | "quiet" | "good" }) {
  const c =
    tone === "bad"
      ? "bg-negative"
      : tone === "warn"
        ? "bg-warning"
        : tone === "good"
          ? "bg-positive"
          : "bg-[var(--gray-400)]"
  return <span aria-hidden className={`inline-block size-2 shrink-0 rounded-full ${c}`} />
}

/** Øverst på hver side: en liten linje, én setning i Newsreader, og ingressen. */
export function PageHeader({
  eyebrow,
  title,
  lead,
  aside,
}: {
  eyebrow?: ReactNode
  title: ReactNode
  lead?: ReactNode
  aside?: ReactNode
}) {
  return (
    <header className="arv-rise flex flex-wrap items-end justify-between gap-x-8 gap-y-4 pt-8">
      <div className="max-w-[720px] min-w-0">
        {eyebrow && <div className="label mb-4 flex flex-wrap items-baseline gap-x-3">{eyebrow}</div>}
        <h1 className="font-heading text-[clamp(32px,4vw,48px)] leading-[1.07] tracking-[-0.025em] text-pretty">
          {title}
        </h1>
        {lead && (
          <p className="text-[var(--gray-700)] dark:text-[var(--gray-300)] mt-4 max-w-[640px] text-[17px] leading-[27px] text-pretty">
            {lead}
          </p>
        )}
      </div>
      {aside && <div className="flex shrink-0 flex-wrap gap-2">{aside}</div>}
    </header>
  )
}

/** Overskrift på en blokk: Newsreader i 24 px, med en grå linje til høyre. */
export function SectionHead({
  title,
  aside,
  id,
}: {
  title: ReactNode
  aside?: ReactNode
  id?: string
}) {
  return (
    <div className="mb-6 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
      <h2 id={id} className="font-heading text-[26px] leading-tight tracking-[-0.015em]">
        {title}
      </h2>
      {aside && <span className="text-muted-foreground text-[13px]">{aside}</span>}
    </div>
  )
}
