/* Forsidekortene: ett tall, formen det har hatt, og én setning om hva det betyr.
 *
 * Hvert kort er én serie, så ingen av dem trenger tegnforklaring — overskriften
 * sier hva linja er. Fargen bærer bare fortegn: merkegrønt er en verdi over
 * null, rød er under. Selve tallet står i tekstfarge, slik at kortene leses som ett sett
 * og ikke som fire forskjellige grafer. Paret er kjørt gjennom fargevalidatoren
 * i begge moduser. */
import { Bar, BarChart, Line, LineChart, YAxis } from "recharts"

import { Card, CardContent } from "@/components/ui/card"
import { ChartContainer, ChartTooltip } from "@/components/ui/chart"
import type { ChartConfig } from "@/components/ui/chart"
import { Skeleton } from "@/components/ui/skeleton"
import { kr } from "@/lib/format"

export type Point = { month: string; value: number | null }

const config = {
  value: { label: "verdi", color: "var(--chart-committed)" },
} satisfies ChartConfig

const POS = "var(--chart-committed)"
const NEG = "var(--chart-negative)"

/** Runder enden som peker bort fra nullinja, slik at søyla står på grunnlinja.
 *  Inneværende måned er ikke ferdig, og tegnes tonet ned så den ikke leses som
 *  et fall. */
function Column(props: {
  x?: number; y?: number; width?: number; height?: number; value?: number
  index?: number; last?: number; partial?: boolean
}) {
  const { x = 0, y = 0, width = 0, height = 0, value = 0 } = props
  const dim = props.partial && props.index === props.last
  const h = Math.abs(height)
  const r = Math.min(4, width / 2, h)
  const up = value >= 0
  // To piksler luft mellom nabosøyler, slik at hver måned leses for seg.
  const w = Math.max(1, width - 2)
  const left = x + 1
  const top = height < 0 ? y + height : y
  const d = up
    ? `M${left},${top + h} V${top + r} a${r},${r} 0 0 1 ${r},-${r} h${w - 2 * r} a${r},${r} 0 0 1 ${r},${r} V${top + h} Z`
    : `M${left},${top} V${top + h - r} a${r},${r} 0 0 0 ${r},${r} h${w - 2 * r} a${r},${r} 0 0 0 ${r},-${r} V${top} Z`
  return <path d={d} fill={up ? POS : NEG} fillOpacity={dim ? 0.4 : 1} />
}

function Hover({ active, payload, suffix, partialMonth }: {
  active?: boolean
  payload?: { payload: Point }[]
  suffix: string
  partialMonth?: string
}) {
  const p = payload?.[0]?.payload
  if (!active || !p || p.value == null) return null
  return (
    <div className="bg-popover grid gap-0.5 rounded-md border px-3 py-2 text-xs">
      <span className="text-muted-foreground">
        {p.month}
        {p.month === partialMonth && " · så langt"}
      </span>
      <span className="font-medium tabular-nums">
        {kr(p.value)} {suffix}
      </span>
    </div>
  )
}

export function MetricCard({
  label,
  value,
  series,
  note,
  kind = "bar",
  suffix = "kr",
  loading,
  partial,
}: {
  label: string
  value: string
  series: Point[]
  note: React.ReactNode
  kind?: "bar" | "line"
  suffix?: string
  loading?: boolean
  /** Siste måned er inneværende og ikke ferdig. Gjelder bevegelser, ikke saldoer. */
  partial?: boolean
}) {
  const data = series.filter((p) => p.value != null)
  const span =
    data.length > 1 ? `${data[0].month}–${data[data.length - 1].month}` : ""
  const partialMonth = partial && data.length ? data[data.length - 1].month : undefined

  return (
    <Card size="sm" className="gap-4 px-1">
      <CardContent className="grid gap-4">
        <div className="grid gap-2">
          {/* Perioden står oppe ved etiketten. Nede ved setningen presset den
              setningen over tre linjer i et smalt kort. */}
          <div className="flex items-baseline justify-between gap-3">
            <span className="label">{label}</span>
            {span && <span className="text-muted-foreground shrink-0 text-xs">{span}</span>}
          </div>
          {loading ? (
            <Skeleton className="h-9 w-28" />
          ) : (
            <span className="text-[34px] leading-none font-light tracking-[-0.03em] tabular-nums">
              {value}
            </span>
          )}
        </div>

        {loading ? (
          <Skeleton className="h-14 w-full" />
        ) : data.length > 1 ? (
          <ChartContainer config={config} className="h-14 w-full">
            {kind === "bar" ? (
              <BarChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                <YAxis hide domain={[(min: number) => Math.min(0, min), "auto"]} />
                <ChartTooltip
                  cursor={false}
                  content={<Hover suffix={suffix} partialMonth={partialMonth} />}
                />
                <Bar
                  dataKey="value"
                  shape={<Column last={data.length - 1} partial={partial} />}
                  isAnimationActive={false}
                />
              </BarChart>
            ) : (
              <LineChart data={data} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
                <YAxis hide domain={["dataMin", "dataMax"]} />
                <ChartTooltip cursor={false} content={<Hover suffix={suffix} />} />
                <Line
                  dataKey="value"
                  stroke={POS}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                />
              </LineChart>
            )}
          </ChartContainer>
        ) : (
          <div className="border-border flex h-14 items-end border-b border-dashed pb-2">
            <span className="text-muted-foreground text-[13px]">
              Utviklingen kommer når flere måneder er bokført
            </span>
          </div>
        )}

        <p className="text-muted-foreground text-[13px] leading-5 text-pretty">{note}</p>
      </CardContent>
    </Card>
  )
}
