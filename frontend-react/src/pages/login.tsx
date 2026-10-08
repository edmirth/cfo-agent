/* Innloggingen. Bare daglig leder har konto; ingen kan registrere seg selv.
 * Passord, eller en lenke på e-post for den som ikke vil huske et. */
import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { supabase } from "@/lib/auth"

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
    <div className="flex min-h-svh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardContent className="grid gap-5">
          <div>
            <p className="text-muted-foreground mb-2 font-mono text-[11px] tracking-[0.16em] uppercase">
              CFO
            </p>
            <h1 className="font-heading text-2xl font-semibold tracking-tight">Logg inn</h1>
          </div>

          {sent ? (
            <p className="text-sm leading-relaxed">
              Sjekk e-posten. Lenken vi sendte til <b>{email}</b> logger deg inn.
            </p>
          ) : (
            <form onSubmit={withPassword} className="grid gap-3">
              <Input
                type="email"
                autoComplete="email"
                placeholder="E-post"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
              <Input
                type="password"
                autoComplete="current-password"
                placeholder="Passord"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {error && <p className="text-destructive text-sm">{error}</p>}
              <Button type="submit" disabled={busy || !password}>
                {busy ? "Logger inn …" : "Logg inn"}
              </Button>
              <Button
                type="button"
                variant="link"
                className="h-auto p-0 text-sm"
                onClick={withLink}
                disabled={busy}
              >
                Send meg en innloggingslenke i stedet
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
