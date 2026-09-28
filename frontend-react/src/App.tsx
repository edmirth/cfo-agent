import { useEffect, useState } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { api, get } from "@/lib/api"
import { Brief } from "@/pages/brief"
import { Chat } from "@/pages/chat"
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

function Shell() {
  const hash = useHash()
  useTheme()
  const [company, setCompany] = useState("CFO")
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
        route={hash}
        company={company}
        sakerCount={sakerCount}
        conversations={convs}
        activeId={activeId}
        onDelete={remove}
      />
      <SidebarInset>
        {/* Forsiden er et oppslag med fire kort ved siden av hverandre og
            trenger bredden. Chatten er tekst og skal beholde lesebredden. */}
        <div
          className={`mx-auto w-full px-6 pt-4 pb-20 ${
            onChat ? "max-w-4xl" : "max-w-6xl"
          }`}
        >
          {onChat ? (
            <Chat conv={conv} />
          ) : hash === "#saker" ? (
            <Saker onCount={setSakerCount} />
          ) : hash === "#selskapet" ? (
            <Selskapet />
          ) : (
            <Brief />
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}

export default function App() {
  return (
    <ConversationsProvider>
      <Shell />
    </ConversationsProvider>
  )
}
