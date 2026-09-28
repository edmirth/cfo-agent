/* Det eneste på forsiden som er skrevet, ikke regnet ut. Teksten kommer fra
 * CFO-en selv og skrives én gang i døgnet — derfor daterer kortet seg selv, og
 * derfor sier det fra når det viser gårsdagens tekst. */
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { Summary } from "@/lib/api"
import { dateNo } from "@/lib/format"

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
  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase">
            CFO-en om driften
          </span>
          {data?.verdict && (
            <Badge variant="secondary" className="h-4 px-1.5 text-[9px] uppercase">
              {data.verdict}
            </Badge>
          )}
          {data?.stale && (
            <span className="text-muted-foreground/70 font-mono text-[10px]">
              fra {data.written ? dateNo(data.written) : "sist"}
            </span>
          )}
        </div>

        {loading || refreshing ? (
          <div className="grid gap-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-[92%]" />
            <Skeleton className="h-4 w-[97%]" />
            <Skeleton className="h-4 w-[64%]" />
          </div>
        ) : data?.text ? (
          <p className="text-[15px] leading-relaxed text-pretty">{data.text}</p>
        ) : data?.error ? (
          <p className="text-muted-foreground text-sm">{data.error}</p>
        ) : (
          <p className="text-muted-foreground text-sm">
            Ingen oppsummering i dag. Tallene under står som de skal.
          </p>
        )}

        <div className="mt-auto flex items-center gap-4 pt-1">
          <Button variant="link" className="h-auto p-0 text-sm" onClick={onAsk}>
            Spør om dette →
          </Button>
          <Button
            variant="link"
            className="text-muted-foreground h-auto p-0 text-xs"
            onClick={onRefresh}
            disabled={refreshing}
          >
            Skriv på nytt
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
