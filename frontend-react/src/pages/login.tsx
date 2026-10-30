/* Innloggingen. Bare daglig leder har konto; ingen kan registrere seg selv.
 * Passord, eller en lenke på e-post for den som ikke vil huske et.
 *
 * En dør, ikke en utstilling: her skal ingen overtales til noe. Siden arver
 * appens egne tokens, og bildet ved siden av er merkets dokumentariske
 * standard (varm mono) i en 6 px ramme. På mobil står bare skjemaet. */
import { useId, useState, type FormEvent } from "react"

import { Wordmark } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AFTER_LOGIN, supabase } from "@/lib/auth"

/** Supabase svarer på engelsk. Det daglig leder trenger å vite, på norsk. */
function said(message: string): string {
  if (/invalid login credentials/i.test(message)) return "Feil e-post eller passord."
  if (/email not confirmed/i.test(message)) return "E-postadressen er ikke bekreftet ennå."
  if (/signups not allowed|user not found/i.test(message))
    return "Denne e-postadressen har ikke tilgang."
  if (/rate limit|too many/i.test(message)) return "For mange forsøk. Vent litt og prøv igjen."
  return "Innloggingen feilet. Prøv igjen."
}

export function Login({ denied }: { denied?: string | null }) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(denied ?? null)
  const [sent, setSent] = useState(false)
  const emailId = useId()
  const passwordId = useId()

  const withPassword = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const { error } = await supabase().auth.signInWithPassword({ email, password })
    if (error) setError(said(error.message))
    setBusy(false)
  }

  const withLink = async () => {
    if (!email) {
      setError("Skriv inn e-postadressen først.")
      return
    }
    setBusy(true)
    setError(null)
    // Lenken i e-posten fører til forsiden, så det man kom for (en sak fra
    // mandagsbrevet, #saker/K016) huskes her og hentes fram etter innloggingen.
    // Kan åpnes i en annen fane, derfor localStorage og ikke sessionStorage.
    try {
      if (window.location.hash) localStorage.setItem(AFTER_LOGIN, window.location.hash)
    } catch {
      // Uten lagring havner man på forsiden, som før.
    }
    const { error } = await supabase().auth.signInWithOtp({
      email,
      // Ingen ny konto av en lenke: bare den som allerede har tilgang, får en.
      options: { shouldCreateUser: false, emailRedirectTo: window.location.origin },
    })
    if (error) setError(said(error.message))
    else setSent(true)
    setBusy(false)
  }

  return (
    <div className="grid min-h-svh lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <main className="flex flex-col px-5 py-8 sm:px-12 lg:px-20">
        <Wordmark className="text-[28px]" />
        <div className="arv-rise my-auto w-full max-w-[380px] py-12">
          <div className="grid gap-9">
            <div className="grid gap-3">
                <h1 className="font-heading text-[44px] leading-[1.05] tracking-[-0.025em]">
                  {sent ? "Sjekk e-posten." : "Logg inn."}
                </h1>
                <p className="text-muted-foreground text-[15px] leading-6">
                  {sent
                    ? "Lenken logger deg inn uten passord."
                    : "Tilgang er personlig. Ingen kan registrere seg selv."}
                </p>
            </div>

            {sent ? (
              <div className="grid gap-5">
                <div className="grid gap-2">
                  <p className="text-sm leading-relaxed">
                    Vi har sendt en innloggingslenke til{" "}
                    <span className="font-medium">{email}</span>. Åpne den i denne nettleseren,
                    så er du inne.
                  </p>
                  <p className="text-muted-foreground text-[13px] leading-relaxed">
                    Lenken virker én gang. Ligger den ikke i innboksen, se i søppelposten.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  className="w-full"
                  onClick={() => setSent(false)}
                >
                  Bruk passord i stedet
                </Button>
              </div>
            ) : (
              <form onSubmit={withPassword} className="grid gap-5">
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <label htmlFor={emailId} className="text-[13px] font-medium">
                      E-post
                    </label>
                    <Input
                      id={emailId}
                      type="email"
                      autoComplete="email"
                      autoFocus
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                    />
                  </div>
                  <div className="grid gap-2">
                    <label htmlFor={passwordId} className="text-[13px] font-medium">
                      Passord
                    </label>
                    <Input
                      id={passwordId}
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                  </div>
                </div>

                {/* Sagt høyt for skjermlesere også: feilen kommer etter at
                    knappen er trykket, og da er fokus et annet sted. */}
                {error && (
                  <p role="alert" className="text-bad-text text-[13px] leading-5">
                    {error}
                  </p>
                )}

                <Button type="submit" className="w-full" disabled={busy}>
                  {busy ? "Logger inn …" : "Logg inn"}
                </Button>

                {/* Lenka på e-post er en likeverdig vei inn, ikke en
                    bortgjemt utvei, så den ser ut som en knapp. */}
                <div className="flex items-center gap-3" aria-hidden="true">
                  <span className="bg-border h-px flex-1" />
                  <span className="text-muted-foreground text-xs">eller</span>
                  <span className="bg-border h-px flex-1" />
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  className="w-full"
                  onClick={withLink}
                  disabled={busy}
                >
                  Send meg en innloggingslenke
                </Button>
              </form>
            )}
          </div>
        </div>
        <p className="text-muted-foreground text-xs">
          Arvaka leser regnskapet deres. Endrer ingenting.
        </p>
      </main>
      <aside className="hidden p-3 lg:block" aria-hidden="true">
        <div className="relative h-full overflow-hidden rounded-md">
          <img
            src="/brand/arvaka-mono-building.jpg"
            alt=""
            className="absolute inset-0 size-full object-cover"
          />
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#0F0E0D]/70 to-transparent p-10 pt-32">
            <p className="font-heading max-w-[18ch] text-[34px] leading-[1.1] tracking-[-0.02em] text-[var(--ivory)]">
              Bokføringen ser bakover. Arvaka ser fremover.
            </p>
          </div>
        </div>
      </aside>
    </div>
  )
}
