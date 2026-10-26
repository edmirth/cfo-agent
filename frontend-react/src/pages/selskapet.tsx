import { useEffect, useState } from "react"

import { PageHeader, SectionHead } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api, get } from "@/lib/api"
import type { Rule, Rules } from "@/lib/api"
import { kr, pct } from "@/lib/format"
import { authFetch } from "@/lib/auth"

type Company = {
  exists: boolean
  text: string
  settings: Record<string, string | number>
  notes: string[]
  used_in_calculations: string[]
  known_settings: Record<string, string>
}

/** En regel slik den brukes, med enheten den har. */
const ruleValue = (key: string, r: Rule) => {
  if (r.value == null) return null
  if (key.endsWith("_kr")) return `${kr(r.value)} kr`
  if (key.endsWith("_pct")) return pct(r.value, r.value % 1 ? 1 : 0)
  if (key.endsWith("_dager")) return `${r.value} dager`
  return String(r.value)
}

export function Selskapet() {
  const [text, setText] = useState("")
  const [co, setCo] = useState<Company | null>(null)
  const [status, setStatus] = useState<{ msg: string; tone: "" | "ok" | "bad" }>({
    msg: "",
    tone: "",
  })
  const [saving, setSaving] = useState(false)
  // Reglene slik beregningene faktisk bruker dem nå — med standardverdien der
  // selskapet ikke har satt noe, så «ikke satt» aldri betyr «ingen regel».
  const [rules, setRules] = useState<Rules | null>(null)
  const loadRules = () =>
    api
      .rules()
      .then((r) => setRules(r.rules))
      .catch(() => setRules(null))

  useEffect(() => {
    loadRules()
  }, [])

  useEffect(() => {
    get<Company>("/api/company")
      .then((d) => {
        setCo(d)
        setText(d.text || "")
      })
      .catch(() => setStatus({ msg: "Fikk ikke hentet teksten.", tone: "bad" }))
  }, [])

  const save = async () => {
    setSaving(true)
    setStatus({ msg: "Lagrer …", tone: "" })
    try {
      const r = await authFetch("/api/company", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })
      if (!r.ok) throw new Error((await r.text()).slice(0, 200))
      setCo(await r.json())
      loadRules()
      setStatus({ msg: "Lagret. Arvaka bruker den fra neste spørsmål.", tone: "ok" })
    } catch (e) {
      setStatus({ msg: "Kunne ikke lagre: " + (e as Error).message, tone: "bad" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-14">
      <PageHeader
        eyebrow="Om selskapet"
        title="Det regnskapet ikke kan fortelle."
        lead="Arvaka leser dette hver gang den svarer. Skriv hvordan dere faktisk jobber — når lønnen utbetales, hvem kundene er, hvilke måneder som alltid er tunge. Det avgjør om et tall leses som et problem eller som en helt vanlig måned."
      />

      {/* På en bred skjerm står innstillingene ved siden av teksten de leses
          fra, i stedet for under den med tomrom til høyre. Først fra 2xl:
          teksten er brutt for hånd rundt 72 tegn, og et smalere felt brøt
          linjene en gang til midt i setningen. */}
      <div className="grid gap-14 2xl:grid-cols-[minmax(0,1fr)_minmax(340px,420px)] 2xl:gap-x-16">
        <section>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            rows={24}
            aria-label="Om selskapet"
            className="min-h-[60vh] resize-y p-5 font-[ui-monospace,SFMono-Regular,Menlo,monospace] text-[13px] leading-6"
          />
          <div className="mt-4 flex items-center gap-4">
            <Button onClick={save} disabled={saving}>
              Lagre
            </Button>
            <span
              className={
                "text-sm " +
                (status.tone === "ok"
                  ? "text-good-text"
                  : status.tone === "bad"
                    ? "text-bad-text"
                    : "text-muted-foreground")
              }
            >
              {status.msg}
            </span>
          </div>
        </section>

        <section>
          <SectionHead title="Innstillinger som flytter tall" />
          <p className="text-muted-foreground -mt-2 mb-6 max-w-[62ch] text-[15px] leading-6">
            Linjene mellom <code className="bg-muted rounded-sm px-1 py-0.5 font-[ui-monospace,SFMono-Regular,Menlo,monospace] text-[13px]">---</code>{" "}
            øverst i teksten. Alt annet leses av Arvaka, men endrer ingen regnestykker.
          </p>
          <ul className="divide-border divide-y border-y text-sm">
            {Object.entries(co?.known_settings || {}).map(([key, what]) => {
              const value = co?.settings?.[key]
              const rule = rules?.[key as keyof Rules]
              const used = rule && ruleValue(key, rule)
              return (
                <li key={key} className="grid gap-1 py-3.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <code className="font-[ui-monospace,SFMono-Regular,Menlo,monospace] text-[13px]">{key}</code>
                    <b className="font-medium tabular-nums">
                      {value != null ? (
                        // A rule the company set reads with its unit, «2 000 000 kr», not 2000000.
                        rule && !rule.assumed && used ? used : value
                      ) : (
                        <span className="text-muted-foreground font-sans font-normal">
                          ikke satt
                          {rule?.assumed && used
                            ? ` · bruker ${used} (${rule.basis === "standard" ? "standard" : rule.basis})`
                            : ""}
                        </span>
                      )}
                    </b>
                  </div>
                  <span className="text-muted-foreground text-[13px] leading-5 text-pretty">{what}</span>
                </li>
              )
            })}
          </ul>
          {!!co?.notes?.length && (
            <div className="text-bad-text mt-5 rounded-md bg-[color-mix(in_oklab,var(--negative)_10%,transparent)] px-4 py-3 text-sm">
              {co.notes.map((n, i) => (
                <p key={i}>{n}</p>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
