/* Mandagsbrevet: det første daglig leder leser om pengene hver uke. Fargen og
 * tallene er regnet ut; bare setningen og endringene er skrevet av CFO-en.
 * Samme tekst som lagres og senere sendes på e-post. */
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { WeeklyBrief } from "@/lib/api"
import { dateNo, kr } from "@/lib/format"

const LIGHT = {
  green: { word: "Grønn", color: "var(--color-emerald-600, #059669)" },
  yellow: { word: "Gul", color: "var(--color-amber-500, #f59e0b)" },
  red: { word: "Rød", color: "var(--destructive)" },
} as const

function Label({ children }: { children: ReactNode }) {
  return (
    <p className="text-muted-foreground mb-1.5 font-mono text-[10px] tracking-[0.12em] uppercase">
      {children}
    </p>
  )
}

export function WeeklyBriefCard({
  data,
  loading,
  onWrite,
  writing,
}: {
  data?: WeeklyBrief | null
  loading?: boolean
  onWrite: () => void
  writing?: boolean
}) {
  if (loading || writing) {
    return (
      <Card>
        <CardContent className="grid gap-2">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-[85%]" />
        </CardContent>
      </Card>
    )
  }
  if (!data) {
    return (
      <Card>
        <CardContent className="flex flex-wrap items-baseline justify-between gap-3">
          <p className="text-muted-foreground text-sm">
            Mandagsbrevet skrives første virkedag hver uke kl 07. Det er ikke skrevet ennå.
          </p>
          <Button variant="link" className="h-auto p-0 text-sm" onClick={onWrite}>
            Skriv det nå
          </Button>
        </CardContent>
      </Card>
    )
  }

  const light = LIGHT[data.light]
  const d = data.decisions
  return (
    <Card className="border-l-4" style={{ borderLeftColor: light.color }}>
      <CardContent className="grid gap-5">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase">
              Mandagsbrevet · uke {data.period.split("-W")[1]}
            </span>
            {!data.current && (
              <span className="text-muted-foreground/70 font-mono text-[10px]">
                fra {dateNo(data.made_on)}
              </span>
            )}
          </div>
          <p className="text-[17px] leading-snug font-semibold text-pretty">
            <span className="mr-2 inline-flex items-center gap-1.5 align-[1px]">
              <span
                aria-hidden
                className="inline-block size-2.5 rounded-full"
                style={{ background: light.color }}
              />
              <span className="font-mono text-xs tracking-[0.1em] uppercase">{light.word}</span>
            </span>
            {data.sentence}
          </p>
          <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
            {data.low_point.text}
          </p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <Label>Endret siden forrige mandag</Label>
            {data.changed.length ? (
              <ul className="grid gap-1 text-sm leading-relaxed">
                {data.changed.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground text-sm">Ingen endringer verdt å nevne.</p>
            )}
          </div>
          <div>
            <Label>{d.count ? `Trenger deg (${d.count})` : "Trenger deg"}</Label>
            {d.count ? (
              <ul className="grid gap-1 text-sm leading-relaxed">
                {d.top.map((c) => (
                  <li key={c.id}>
                    <a href={c.link} className="underline-offset-4 hover:underline">
                      {c.title}
                    </a>
                    {c.amount ? (
                      <span className="text-muted-foreground font-mono text-xs tabular-nums">
                        {" "}
                        · {kr(c.amount)} kr
                      </span>
                    ) : null}
                  </li>
                ))}
                {d.more > 0 && (
                  <li>
                    <a href="#saker" className="text-muted-foreground underline-offset-4 hover:underline">
                      og {d.more} til under Saker
                    </a>
                  </li>
                )}
              </ul>
            ) : (
              <p className="text-sm">Ingenting trenger deg denne uka.</p>
            )}
          </div>
        </div>

        <div className="text-muted-foreground grid gap-1 border-t pt-3 text-xs leading-relaxed">
          <p>
            {data.books.text}
            {data.books.lines.length > 0 && " " + data.books.lines.join(" ")}
          </p>
          <p>{data.accuracy.text}</p>
          {data.written_by === "engine" && (
            <p>Skrevet ut fra tallene alene denne gangen — CFO-en fikk ikke skrevet sine egne ord.</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
