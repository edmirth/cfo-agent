/* Spørsmålet om måling (kort 37): stilles én gang, første gang noen logger inn,
 * og kan endres på Selskapet. Ja og nei er like store og like enkle: et nei
 * skal ikke koste mer enn et ja. */
import { useState } from "react"

import { Button } from "@/components/ui/button"

export function ConsentPrompt({ onAnswer }: { onAnswer: (measure: boolean) => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const answer = async (measure: boolean) => {
    setBusy(true)
    try {
      await onAnswer(measure)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div
      role="dialog"
      aria-labelledby="consent-title"
      className="border-border bg-card fixed inset-x-4 bottom-4 z-50 mx-auto max-w-[520px] rounded-2xl border p-5 shadow-lg"
    >
      <h2 id="consent-title" className="font-heading text-[19px] leading-snug">
        Hjelp oss å gjøre Arvaka bedre
      </h2>
      <p className="text-muted-foreground mt-2 text-[14px] leading-6">
        Får vi telle hvor mange minutter du bruker i appen, og når du trykker på en lenke i
        mandagsbrevet? Vi ser aldri hva du leser. Du kan ombestemme deg når som helst under
        Selskapet. <a href="https://arvaka.no/personvern/" className="underline">Personvern</a>
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Button variant="outline" disabled={busy} onClick={() => answer(true)}>
          Ja, gjerne
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => answer(false)}>
          Nei takk
        </Button>
      </div>
    </div>
  )
}
