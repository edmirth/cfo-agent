/* Innlogging. Supabase logger inn; serveren avgjør hvem som slipper inn.
 * Alt som snakker med /api går gjennom authFetch, som legger ved tokenet og
 * sier fra når serveren vil ha en ny innlogging. Byttes leverandør, er det
 * denne fila som endres. */
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js"

type Config = { enabled: false } | { enabled: true; url: string; anon_key: string }

let client: SupabaseClient | null = null
let enabled = true
const listeners = new Set<(why?: string) => void>()

/** Henter oppsettet fra serveren og lager klienten. Kalles én gang, før appen tegnes. */
/** Der man skulle (#saker/K016), husket mens en innloggingslenke er på vei. */
export const AFTER_LOGIN = "arvaka:etter-innlogging"

export async function initAuth(): Promise<{ enabled: boolean }> {
  const res = await fetch("/api/auth/config")
  if (!res.ok) throw new Error(`/api/auth/config: HTTP ${res.status}`)
  const cfg = (await res.json()) as Config
  enabled = cfg.enabled
  if (cfg.enabled) {
    client = createClient(cfg.url, cfg.anon_key, {
      // PKCE: lenken fra e-posten kommer tilbake med ?code=, ikke i #, som
      // appens egen ruting bruker.
      auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true },
    })
  }
  return { enabled }
}

export const authEnabled = () => enabled

export function supabase(): SupabaseClient {
  if (!client) throw new Error("Innlogging er ikke satt opp")
  return client
}

export async function currentSession(): Promise<Session | null> {
  if (!client) return null
  const { data } = await client.auth.getSession()
  return data.session
}

/** Kalles når økten er borte, så porten kan vise innloggingen — med grunnen,
 * når serveren ga en. */
export function onLoggedOut(fn: (why?: string) => void) {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** Logg ut. `everywhere` bare når daglig leder selv trykker «Logg ut»: et
 * avvist kall fra én fane skal ikke kaste ut økten i en annen. Supabase sin
 * standard er å logge ut overalt, også øktene i andre faner og nettlesere. */
export async function signOut(why?: string, everywhere = false) {
  await client?.auth.signOut({ scope: everywhere ? "global" : "local" })
  listeners.forEach((fn) => fn(why))
}

/** fetch mot /api, med innloggingen lagt ved. Et 401 betyr at økten er borte,
 * et 403 at kontoen ikke har tilgang: begge logger ut her, og porten viser
 * innloggingen igjen med det serveren sa. */
export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (enabled) {
    const session = await currentSession()
    if (session) headers.set("Authorization", `Bearer ${session.access_token}`)
  }
  const res = await fetch(input, { ...init, headers })
  if (enabled && (res.status === 401 || res.status === 403)) {
    const body = await res.clone().json().catch(() => null)
    await signOut(res.status === 403 ? body?.error : undefined)
  }
  return res
}
