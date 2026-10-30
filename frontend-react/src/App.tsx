import { useEffect, useRef, useState } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { Wordmark } from "@/components/brand"
import { ConsentPrompt } from "@/components/consent-prompt"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { api, get } from "@/lib/api"
import { AFTER_LOGIN, authEnabled, authFetch, initAuth, onLoggedOut, supabase } from "@/lib/auth"
import { getConsent, sendTap, setConsent, takeTap, type Tap } from "@/lib/measure"
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

/** Kort 37: spør om måling første gang, og meld fra om et trykk fra
 * mandagsbrevet: med en gang ved et ja, etter svaret om brukeren ikke er spurt
 * ennå, og aldri ved et nei. Serveren lagrer uansett ingenting uten et ja. */
function useMeasure() {
  const [asking, setAsking] = useState(false)
  const pending = useRef<Tap | null>(null)
  useEffect(() => {
    pending.current ??= takeTap()
    getConsent()
      .then((yes) => {
        if (yes === null) return setAsking(true)
        if (yes && pending.current) sendTap(pending.current)
        pending.current = null
      })
      .catch(() => {})
  }, [])
  const answer = async (measure: boolean) => {
    await setConsent(measure)
    setAsking(false)
    if (measure && pending.current) sendTap(pending.current)
    pending.current = null
  }
  return { asking, answer }
}

/** Tid i appen, for produkteieren (#maling): ett signal i minuttet mens
 * appen er synlig og i fokus. Bare at den er i bruk, ikke hva som leses, og
 * serveren tar bare vare på det for den som har sagt ja. */
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
  const { asking, answer } = useMeasure()
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
        {/* Sidene bruker bredden skjermen gir, opp til 1440 px: på en stor
            skjerm sto alt før i en smal stripe midt på med tomrom på begge
            sider. Luften rundt vokser med skjermen. Chatten er tekst og skal
            beholde lesebredden. */}
        <div
          className={`mx-auto w-full px-5 pt-4 pb-24 ${
            onChat ? "max-w-4xl sm:px-10" : "max-w-[1440px] sm:px-8 lg:px-12 2xl:px-16"
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
        {asking && <ConsentPrompt onAnswer={answer} />}
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
          // Og kom man fra en lenke til en sak, er det dit man skal, med
          // mandagsbrevets merke (?fra=brev&b=…) så trykket telles.
          const before = window.location.hash
          let kept = before
          try {
            kept = localStorage.getItem(AFTER_LOGIN) || before
            localStorage.removeItem(AFTER_LOGIN)
          } catch {
            // Uten lagring havner man på forsiden.
          }
          window.history.replaceState(null, "", window.location.pathname + kept)
          if (window.location.hash !== before) {
            window.dispatchEvent(new HashChangeEvent("hashchange"))
          }
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
