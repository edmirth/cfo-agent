/* Det eneste på forsiden som er skrevet, ikke regnet ut. Teksten kommer fra
 * Arvaka selv og skrives én gang i døgnet — derfor daterer blokken seg selv,
 * og derfor sier den fra når den viser gårsdagens tekst.
 *
 * Satt som prosa, ikke som et kort: høyst 640 px bred, første setning i
 * Newsreader, resten i Geist 18/28. */
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { Summary } from "@/lib/api"
import { dateNo } from "@/lib/format"

/** Første setning for seg, så den kan stå større. Er den for lang til å stå
 *  i Newsreader, deles den ved første kolon («Dette året går ikke i balanse:
 *  …»). Lar den seg ikke dele, står alt som brødtekst. */
function lead(text: string): [string, string] {
  const s = text.match(/^(.{20,200}?[.!?])\s+(.+)$/s)
  if (s) return [s[1], s[2]]
  const c = text.match(/^(.{12,120}?):\s+(.+)$/s)
  if (c) return [c[1] + ".", c[2].charAt(0).toUpperCase() + c[2].slice(1)]
  return ["", text]
}

export function SummaryCard({
  data,
  loading,
  onRefresh,
  onAsk,
  refreshing,
}: {
  data?: Summary
  loading?: boolean
  onRefresh: () => void
  onAsk: () => void
  refreshing?: boolean
}) {
  const [first, rest] = data?.text ? lead(data.text) : ["", ""]
  return (
    <div className="max-w-[640px]">
      <div className="label mb-5 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>Arvaka om driften</span>
        {data?.verdict && <Badge>{data.verdict.charAt(0).toUpperCase() + data.verdict.slice(1)}</Badge>}
        {data?.stale && <span>fra {data.written ? dateNo(data.written) : "sist"}</span>}
      </div>

      {loading || refreshing ? (
        <div className="grid gap-3">
          <Skeleton className="h-8 w-[90%]" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-[96%]" />
          <Skeleton className="h-4 w-[70%]" />
        </div>
      ) : data?.text ? (
        <>
          {first && (
            <p className="font-heading text-[28px] leading-[1.2] tracking-[-0.015em] text-pretty">
              {first}
            </p>
          )}
          {rest && (
            <p className={`text-[var(--gray-700)] dark:text-[var(--gray-300)] text-[18px] leading-[28px] text-pretty ${first ? "mt-4" : ""}`}>
              {rest}
            </p>
          )}
        </>
      ) : data?.error ? (
        <p className="text-muted-foreground text-[15px]">{data.error}</p>
      ) : (
        <p className="text-muted-foreground text-[15px]">
          Ingen oppsummering i dag. Tallene står som de skal.
        </p>
      )}

      <div className="mt-6 flex items-center gap-6">
        <Button variant="link" onClick={onAsk}>
          Spør om dette →
        </Button>
        <Button
          variant="link"
          className="text-muted-foreground"
          onClick={onRefresh}
          disabled={refreshing}
        >
          Skriv på nytt
        </Button>
      </div>
    </div>
  )
}
