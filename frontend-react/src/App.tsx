import { useEffect, useState } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { Wordmark } from "@/components/brand"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { api, get } from "@/lib/api"
import { authEnabled, authFetch, initAuth, onLoggedOut, supabase } from "@/lib/auth"
import { Brief } from "@/pages/brief"
import { Chat } from "@/pages/chat"
import { Helsesjekk } from "@/pages/helsesjekk"
import { Login } from "@/pages/login"
import { Maling } from "@/pages/maling"
import { Saker } from "@/pages/saker"
import { Selskapet } from "@/pages/selskapet"
import { ConversationsProvider, useConversations } from "@/store/conversations"

/** Hash-ruting, som i den gamle frontenden: #, #ny, #saker, #selskapet, #c/<id>. */
function useHash() {
  const [hash, setHash] = useState(() => window.location.hash || "#")
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#")
    window.addEventListener("hashchange", on)
    return () => window.removeEventListener("hashchange", on)
  }, [])
  return hash
}

/** Følger systemets fargemodus; shadcn bytter på .dark. */
function useTheme() {
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const on = () => document.documentElement.classList.toggle("dark", mq.matches)
    on()
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
}

/** Tid i appen, for produkteieren (#maling): ett signal i minuttet mens
 * appen er synlig og i fokus. Bare at den er i bruk, ikke hva som leses. */
function useActiveMinutes() {
  useEffect(() => {
    const ping = () => {
      if (document.visibilityState === "visible" && document.hasFocus()) {
        authFetch("/api/activity", { method: "POST" }).catch(() => {})
      }
    }
    ping()
    const id = window.setInterval(ping, 60_000)
    return () => window.clearInterval(id)
  }, [])
}

function Shell() {
  const hash = useHash()
  useTheme()
  useActiveMinutes()
  const [company, setCompany] = useState("")
  const [sakerCount, setSakerCount] = useState(0)
  const { convs, remove } = useConversations()

  useEffect(() => {
    api.health().then((h) => setCompany(h.company)).catch(() => {})
    get<{ open: unknown[] }>("/api/cards")
      .then((d) => setSakerCount(d.open.length))
      .catch(() => {})
  }, [])

  const activeId = hash.startsWith("#c/") ? hash.slice(3) : null
  const conv = convs.find((c) => c.id === activeId) ?? null
  const onChat = hash === "#ny" || hash.startsWith("#c/")

  return (
    <SidebarProvider>
      <AppSidebar
        route={hash.startsWith("#saker/") ? "#saker" : hash}
        company={company}
        sakerCount={sakerCount}
        conversations={convs}
        activeId={activeId}
        onDelete={remove}
      />
      <SidebarInset>
        {/* På mobil ligger menyen bak en knapp; uten denne linja fantes det
            ingen vei inn i den. */}
        <div className="border-border bg-background/95 sticky top-0 z-20 flex h-14 items-center justify-between border-b px-5 backdrop-blur md:hidden">
          <a href="#" aria-label="Til forsiden">
            <Wordmark className="text-[22px]" />
          </a>
          <SidebarTrigger />
        </div>
        {/* Forsiden er et oppslag med fire kort ved siden av hverandre og
            trenger bredden. Chatten er tekst og skal beholde lesebredden. */}
        <div
          className={`mx-auto w-full px-5 pt-4 pb-24 sm:px-10 ${
            onChat ? "max-w-4xl" : "max-w-[1120px]"
          }`}
        >
          {onChat ? (
            <Chat conv={conv} />
          ) : hash === "#saker" || hash.startsWith("#saker/") ? (
            <Saker onCount={setSakerCount} focus={hash.slice("#saker/".length) || null} />
          ) : hash === "#maling" ? (
            // For produkteieren. Ikke i menyen; bak en admin-rolle når kundene
            // logger inn.
            <Maling />
          ) : hash === "#helsesjekk" ? (
            <Helsesjekk />
          ) : hash === "#selskapet" ? (
            <Selskapet />
          ) : (
            <Brief onCount={setSakerCount} />
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}

type Gate = "loading" | "in" | "out" | "broken"

/** Ingenting av appen tegnes før det er klart at noen er logget inn — eller
 * at serveren kjører uten innlogging med vilje. */
function useGate(): { gate: Gate; denied: string | null } {
  const [gate, setGate] = useState<Gate>("loading")
  const [denied, setDenied] = useState<string | null>(null)

  useEffect(() => {
    let unsubscribe = () => {}
    initAuth()
      .then(async ({ enabled }) => {
        if (!enabled) return setGate("in")
        const auth = supabase().auth
        const { data } = await auth.getSession()
        setGate(data.session ? "in" : "out")
        // Lenken fra e-posten kommer tilbake med ?code=. Når den er byttet
        // mot en økt, har den gjort jobben sin og skal ikke ligge i adressen.
        if (data.session && new URLSearchParams(window.location.search).has("code")) {
          window.history.replaceState(null, "", window.location.pathname + window.location.hash)
        }
        const sub = auth.onAuthStateChange((_event, session) => {
          setGate(session ? "in" : "out")
          if (session) setDenied(null)
        })
        unsubscribe = () => sub.data.subscription.unsubscribe()
      })
      .catch(() => setGate("broken"))
    const off = onLoggedOut((why) => {
      setDenied(why ?? null)
      setGate("out")
    })
    return () => {
      unsubscribe()
      off()
    }
  }, [])
  return { gate, denied }
}

export default function App() {
  const { gate, denied } = useGate()
  if (gate === "loading") return null
  if (gate === "broken") {
    return (
      <div className="grid min-h-svh place-content-center gap-6 p-10 text-center">
        <Wordmark className="text-[28px]" />
        <p className="text-muted-foreground text-[15px]">
          Får ikke kontakt med serveren. Last siden på nytt om litt.
        </p>
      </div>
    )
  }
  if (gate === "out" && authEnabled()) return <Login denied={denied} />
  return (
    <ConversationsProvider>
      <Shell />
    </ConversationsProvider>
  )
}
