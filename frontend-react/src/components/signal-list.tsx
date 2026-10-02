/* Det som krever handling, i to høyder.
 *
 * Seks like store kort er en vegg: alt roper like høyt, og da sier rekkefølgen
 * ingenting. Det kritiske står derfor stort, med beløpet som tall man kan lese
 * uten å lese setningen, og resten ligger som sammenslåtte rader man kan skumme
 * og åpne. Fargen er aldri alene om å si hva som haster — plasseringen og
 * fristen sier det samme. */
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { kr } from "@/lib/format"
import { dueIn, split } from "@/lib/signals"
import type { Signal } from "@/lib/signals"

// Notis bruker tekstens dempede farge, ikke kantfargen: en prikk i --border er
// praktisk talt usynlig mot kortet og leses som en tegnefeil, ikke som lav
// prioritet.
const TONE = {
  crit: "var(--destructive)",
  warn: "var(--chart-expected)",
  note: "var(--muted-foreground)",
}

const money = (n?: number) => (n == null ? null : `${kr(n)} kr`)

function Meta({ s, seen }: { s: Signal; seen: boolean }) {
  const due = dueIn(s.due)
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase">
        {s.tag}
      </span>
      {due && (
        <span
          className="font-mono text-[10px] tracking-[0.08em] uppercase"
          style={{ color: s.sev === "note" ? undefined : TONE[s.sev] }}
        >
          · {due}
        </span>
      )}
      {!seen && (
        <Badge variant="secondary" className="h-4 px-1.5 text-[9px] uppercase">
          nytt
        </Badge>
      )}
    </div>
  )
}

/** Det viktigste: stort, med beløpet som tall. */
function Lead({
  s,
  seen,
  onAsk,
}: {
  s: Signal
  seen: boolean
  onAsk: (s: Signal) => void
}) {
  return (
    <Card
      className="border-l-4 gap-2 py-4"
      style={{ borderLeftColor: TONE[s.sev] }}
    >
      <CardContent className="grid gap-2 px-5">
        <Meta s={s} seen={seen} />
        <div className="flex items-baseline justify-between gap-4">
          <h3 className="font-heading min-w-0 text-[16px] leading-snug font-semibold text-pretty">
            {s.title}
          </h3>
          {s.amount != null && (
            <span className="shrink-0 font-mono text-lg font-semibold tabular-nums">
              {money(s.amount)}
            </span>
          )}
        </div>
        <p className="text-muted-foreground text-sm leading-relaxed">{s.body}</p>
        <Button
          variant="link"
          className="mt-1 h-auto justify-self-start p-0 text-sm"
          onClick={() => onAsk(s)}
        >
          Grav i dette →
        </Button>
      </CardContent>
    </Card>
  )
}

/** Resten: én rad hver, åpnes når man vil vite mer. */
function Row({
  s,
  seen,
  onAsk,
}: {
  s: Signal
  seen: boolean
  onAsk: (s: Signal) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="group hover:bg-muted/50 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors">
        <span
          className="size-1.5 shrink-0 rounded-full"
          style={{ background: TONE[s.sev] }}
        />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {s.title}
        </span>
        {!seen && (
          <Badge variant="secondary" className="h-4 shrink-0 px-1.5 text-[9px] uppercase">
            nytt
          </Badge>
        )}
        {s.amount != null && (
          <span className="text-muted-foreground shrink-0 font-mono text-xs tabular-nums">
            {money(s.amount)}
          </span>
        )}
        <span className="text-muted-foreground shrink-0 text-xs transition-transform group-data-[state=open]:rotate-180">
          ▾
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pt-1 pb-3 pl-[1.6rem]">
        <Meta s={s} seen={seen} />
        <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
          {s.body}
        </p>
        <Button
          variant="link"
          className="mt-1 h-auto p-0 text-sm"
          onClick={() => onAsk(s)}
        >
          Grav i dette →
        </Button>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function SignalList({
  signals,
  seen,
  onAsk,
}: {
  signals: Signal[]
  seen: Set<string>
  onAsk: (s: Signal) => void
}) {
  const [lead, rest] = split(signals)
  return (
    <div className="grid gap-3">
      {lead.map((s) => (
        <Lead key={s.id} s={s} seen={seen.has(s.id)} onAsk={onAsk} />
      ))}
      {rest.length > 0 && (
        <div className="mt-1">
          <div className="text-muted-foreground mb-1 px-3 font-mono text-[10px] tracking-[0.12em] uppercase">
            {rest.length} til, mindre presserende
          </div>
          <div className="divide-border/60 divide-y rounded-lg ring-1 ring-foreground/10">
            {rest.map((s) => (
              <Row key={s.id} s={s} seen={seen.has(s.id)} onAsk={onAsk} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
