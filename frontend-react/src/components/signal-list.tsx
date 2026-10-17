/* Det som er verdt å følge med på, som én rolig liste.
 *
 * Det ene som trenger en beslutning står allerede øverst i Brief («Trenger
 * deg»). Her ligger resten: én rad hver, rangert, og åpnes når man vil vite
 * mer. Rødt bare for det som er kritisk; prikken sier aldri mer enn
 * plasseringen og fristen sier fra før. */
import { useState } from "react"
import { ChevronDown } from "lucide-react"

import { Dot } from "@/components/brand"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { kr } from "@/lib/format"
import { dueIn } from "@/lib/signals"
import type { Signal } from "@/lib/signals"

const TONE = { crit: "bad", warn: "warn", note: "quiet" } as const

const money = (n?: number) => (n == null ? null : `${kr(n)} kr`)

function Row({ s, seen, onAsk }: { s: Signal; seen: boolean; onAsk: (s: Signal) => void }) {
  const [open, setOpen] = useState(false)
  const due = dueIn(s.due)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="group hover:bg-tint flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors duration-150">
        <Dot tone={TONE[s.sev]} />
        <span className="min-w-0 flex-1 text-[15px] text-pretty">{s.title}</span>
        {!seen && <Badge className="shrink-0">Nytt</Badge>}
        {s.amount != null && (
          <span className="text-muted-foreground hidden shrink-0 text-sm sm:inline">
            {money(s.amount)}
          </span>
        )}
        <ChevronDown className="text-muted-foreground size-4 shrink-0 stroke-[1.5] transition-transform duration-300 group-data-[panel-open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="px-4 pb-5 pl-10">
        <p className="label">
          {s.tag}
          {due && ` · ${due}`}
        </p>
        <p className="text-[var(--gray-700)] dark:text-[var(--gray-300)] mt-1.5 max-w-[68ch] text-[15px] leading-6">
          {s.body}
        </p>
        <Button variant="link" className="mt-2" onClick={() => onAsk(s)}>
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
  return (
    <div className="divide-border divide-y border-y">
      {signals.map((s) => (
        <Row key={s.id} s={s} seen={seen.has(s.id)} onAsk={onAsk} />
      ))}
    </div>
  )
}
