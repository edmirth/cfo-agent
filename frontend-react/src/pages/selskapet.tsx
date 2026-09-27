import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { get } from "@/lib/api"

type Company = {
  exists: boolean
  text: string
  settings: Record<string, string | number>
  notes: string[]
  used_in_calculations: string[]
  known_settings: Record<string, string>
}

export function Selskapet() {
  const [text, setText] = useState("")
  const [co, setCo] = useState<Company | null>(null)
  const [status, setStatus] = useState<{ msg: string; tone: "" | "ok" | "bad" }>({
    msg: "",
    tone: "",
  })
  const [saving, setSaving] = useState(false)

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
      const r = await fetch("/api/company", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })
      if (!r.ok) throw new Error((await r.text()).slice(0, 200))
      setCo(await r.json())
      setStatus({ msg: "Lagret. CFO-en bruker den fra neste spørsmål.", tone: "ok" })
    } catch (e) {
      setStatus({ msg: "Kunne ikke lagre: " + (e as Error).message, tone: "bad" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-8 pt-6">
      <header>
        <p className="text-muted-foreground mb-3 font-mono text-[11px] tracking-[0.16em] uppercase">
          Om selskapet
        </p>
        <h1 className="font-heading text-[30px] leading-tight font-semibold tracking-tight">
          Det regnskapet ikke kan fortelle
        </h1>
        <p className="text-muted-foreground mt-2.5 max-w-[62ch] text-sm">
          CFO-en leser dette hver gang den svarer. Skriv hvordan dere faktisk jobber — når
          lønnen utbetales, hvem kundene er, hvilke måneder som alltid er tunge. Det avgjør
          om et tall leses som et problem eller som en helt vanlig måned.
        </p>
      </header>

      <section>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          rows={24}
          aria-label="Om selskapet"
          className="min-h-[60vh] resize-y p-4 font-mono text-[13px] leading-relaxed"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={save} disabled={saving}>
            Lagre
          </Button>
          <span
            className={
              "text-sm " +
              (status.tone === "ok"
                ? "text-emerald-700 dark:text-emerald-500"
                : status.tone === "bad"
                  ? "text-destructive"
                  : "text-muted-foreground")
            }
          >
            {status.msg}
          </span>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-[17px] font-semibold">Innstillinger som flytter tall</h2>
        <p className="text-muted-foreground mb-4 max-w-[62ch] text-sm">
          Linjene mellom <code className="bg-muted rounded px-1 py-0.5 font-mono">---</code>{" "}
          øverst i teksten. Alt annet leses av CFO-en, men endrer ingen regnestykker.
        </p>
        <ul className="divide-border divide-y border-y text-sm">
          {Object.entries(co?.known_settings || {}).map(([key, what]) => {
            const value = co?.settings?.[key]
            return (
              <li key={key} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5">
                <code className="font-mono text-[13px]">{key}</code>
                <span className="text-muted-foreground flex-1 text-[13px]">{what}</span>
                <b className="font-mono tabular-nums">
                  {value ?? <span className="text-muted-foreground font-sans font-normal">ikke satt</span>}
                </b>
              </li>
            )
          })}
        </ul>
        {!!co?.notes?.length && (
          <div className="border-destructive text-destructive mt-4 rounded border border-l-[3px] px-4 py-3 text-sm">
            {co.notes.map((n, i) => (
              <p key={i}>{n}</p>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
