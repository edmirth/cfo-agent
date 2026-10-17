import { useEffect, useRef, useState } from "react"
import { Check, ChevronDown, Loader2, SendHorizontal } from "lucide-react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { Wordmark } from "@/components/brand"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import type { Preset } from "@/lib/api"
import type { Conversation, Message, Step } from "@/lib/conversations"
import { useConversations } from "@/store/conversations"

/* ── arbeidssporet ────────────────────────────────────────────── */
// Åpent mens det står på, slått sammen til én linje når svaret er ferdig.
function summary(m: Message) {
  const looks = (m.steps || []).reduce((n, s) => n + (s.kind === "tool" ? s.n : 0), 0)
  const secs = m.elapsed ? Math.round(m.elapsed / 1000) : null
  const time =
    secs == null ? "" : secs >= 60 ? ` · ${Math.floor(secs / 60)} min ${secs % 60} s` : ` · ${secs} s`
  return looks ? `${looks} oppslag i regnskapet${time}` : "Tenkte gjennom svaret" + time
}

function status(m: Message) {
  const last = (m.steps || [])[(m.steps || []).length - 1]
  if (last?.kind === "tool") return last.label + (last.n > 1 ? ` ×${last.n}` : "")
  return "Tenker …"
}

function StepRow({ step, live }: { step: Step; live: boolean }) {
  if (step.kind === "tool") {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-[13px]">
        {live ? (
          <Loader2 className="text-good-text size-3.5 animate-spin stroke-[1.5]" />
        ) : (
          <Check className="text-good-text size-3.5 stroke-[1.5]" />
        )}
        {step.label}
        {step.n > 1 && <span className="opacity-70">×{step.n}</span>}
      </div>
    )
  }
  return (
    <p
      className={
        "max-w-[64ch] text-[14px] leading-6 " +
        (step.kind === "think" ? "text-muted-foreground" : "text-foreground/80") +
        (live ? " cfo-sheen" : "")
      }
    >
      {step.text}
    </p>
  )
}

function Work({ m }: { m: Message }) {
  const [open, setOpen] = useState(false)
  const steps = m.steps || []
  if (!steps.length && m.done) return null
  const live = !m.done
  return (
    <Collapsible open={live || open} onOpenChange={setOpen} className="border-border mb-5 border-l pl-4">
      <CollapsibleTrigger
        disabled={live}
        className="text-muted-foreground hover:text-foreground flex w-full items-center gap-2 py-0.5 text-[13px] disabled:cursor-default"
      >
        {live ? (
          <Loader2 className="text-good-text size-3.5 animate-spin stroke-[1.5]" />
        ) : (
          <Check className="text-good-text size-3.5 stroke-[1.5]" />
        )}
        <span className={"flex-1 truncate text-left" + (live ? " cfo-pulse" : "")}>
          {m.done ? summary(m) : status(m)}
        </span>
        {!live && (
          <ChevronDown
            className={"size-3.5 stroke-[1.5] transition-transform duration-300 " + (open ? "rotate-180" : "")}
          />
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="grid gap-2 py-2">
        {steps.map((s, i) => (
          <StepRow key={i} step={s} live={live && i === steps.length - 1} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  )
}

/* ── meldingene ───────────────────────────────────────────────── */
function Bubble({ m }: { m: Message }) {
  if (m.role === "user") {
    return (
      <div className="arv-rise mb-8 flex justify-end">
        <div className="bg-secondary text-foreground max-w-[76%] rounded-xl px-4 py-3 text-[15px] leading-6">
          {m.text}
        </div>
      </div>
    )
  }
  return (
    <div className="mb-10">
      <div className="mb-3">
        <Wordmark className="text-[17px]" />
      </div>
      <Work m={m} />
      {m.text && (
        <div className="cfo-md text-[15.5px] leading-[26px]">
          <Markdown remarkPlugins={[remarkGfm]}>{m.text}</Markdown>
          {!m.done && <span className="cfo-caret" />}
        </div>
      )}
      {m.error && (
        <div className="text-bad-text mt-2 rounded-md bg-[color-mix(in_oklab,var(--negative)_10%,transparent)] px-4 py-3 text-sm">
          {m.error}
        </div>
      )}
    </div>
  )
}

/* ── siden ────────────────────────────────────────────────────── */
export function Chat({ conv }: { conv: Conversation | null }) {
  const { ask, busy } = useConversations()
  const [value, setValue] = useState("")
  const [presets, setPresets] = useState<Preset[]>([])
  const endRef = useRef<HTMLDivElement>(null)
  const working = busy(conv?.id ?? null)

  useEffect(() => {
    api.presets().then((p) => setPresets(p.presets)).catch(() => {})
  }, [])

  // Følg svaret nedover, men bare når leseren allerede står nederst.
  useEffect(() => {
    const near =
      window.innerHeight + window.scrollY > document.body.scrollHeight - 160
    if (near) endRef.current?.scrollIntoView({ block: "end" })
  })

  // Enter sender skjemaet selv om knappen er deaktivert. Å tømme feltet først
  // og spørre etterpå kastet spørsmålet hver gang ask() avviste det — så feltet
  // tømmes først når spørsmålet faktisk er tatt imot.
  const send = (e: React.FormEvent) => {
    e.preventDefault()
    if (ask(value, undefined, !conv)) setValue("")
  }

  return (
    <div className="flex min-h-[calc(100vh-2rem)] flex-col">
      <div className="flex-1 pt-6">
        {!conv || !conv.messages.length ? (
          <div className="arv-rise pt-[14vh]">
            <h2 className="font-heading text-[clamp(34px,4vw,48px)] leading-[1.07] tracking-[-0.025em]">
              Hva lurer du på?
            </h2>
            <p className="text-[var(--gray-700)] dark:text-[var(--gray-300)] mt-4 max-w-[54ch] text-[17px] leading-[27px]">
              Spør om tallene, en kunde, en kostnad eller en plan. Svaret bygger på
              regnskapet deres slik det står i Tripletex nå.
            </p>
            <div className="mt-8 flex flex-wrap gap-2">
              {presets.map((p) => (
                <Button
                  key={p.id}
                  variant="outline"
                  size="sm"
                  onClick={() => ask(p.id, p.label, !conv)}
                >
                  {p.label}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          conv.messages.map((m, i) => <Bubble key={i} m={m} />)
        )}
        <div ref={endRef} />
      </div>

      <div className="bg-background sticky bottom-0 pt-3 pb-4">
        <form
          onSubmit={send}
          className="bg-card border-border focus-within:border-ring flex items-center gap-2 rounded-xl border p-1.5 pl-4 transition-colors duration-150"
        >
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={conv ? "Spør videre …" : "Spør om hva som helst …"}
            autoComplete="off"
            aria-label="Spørsmålet ditt"
            className="h-10 border-0 bg-transparent px-0 text-[15px] focus-visible:ring-0"
          />
          <Button type="submit" size="icon" disabled={working} aria-label="Send">
            <SendHorizontal />
          </Button>
        </form>
        <p className="text-muted-foreground mt-2.5 text-center text-xs">
          Leser regnskapet deres. Endrer ingenting.
        </p>
      </div>
    </div>
  )
}
