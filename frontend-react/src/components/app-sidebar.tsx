import {
  Building2,
  CalendarClock,
  FileText,
  ListChecks,
  LogOut,
  MessageSquare,
  Plus,
  X,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { Monogram, Wordmark } from "@/components/brand"
import { authEnabled, signOut } from "@/lib/auth"
import type { Conversation } from "@/lib/conversations"
import { bucket } from "@/lib/conversations"

type Props = {
  route: string
  company: string
  sakerCount: number
  conversations: Conversation[]
  activeId: string | null
  onDelete: (id: string) => void
}

/* Sammenslått står dette igjen som ikoner — shadcn sin Sidebar gjør selve
   sammenslåingen, og husker tilstanden på tvers av lasting. */
const NAV = [
  { href: "#", key: "home", label: "Brief", icon: CalendarClock },
  { href: "#saker", key: "saker", label: "Saker", icon: ListChecks },
  { href: "#helsesjekk", key: "helsesjekk", label: "Helsesjekk", icon: FileText },
  { href: "#selskapet", key: "selskapet", label: "Selskapet", icon: Building2 },
]

export function AppSidebar({
  route,
  company,
  sakerCount,
  conversations,
  activeId,
  onDelete,
}: Props) {
  // Samtalene grupperes på alder, nyeste først.
  const groups: [string, Conversation[]][] = []
  for (const c of conversations) {
    const g = bucket(c.updated)
    const last = groups[groups.length - 1]
    if (last && last[0] === g) last[1].push(c)
    else groups.push([g, [c]])
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-5 px-4 pt-5 pb-2 group-data-[collapsible=icon]:px-2">
        <div className="flex items-center justify-between gap-2">
          <a href="#" aria-label="Arvaka, til forsiden" className="group-data-[collapsible=icon]:hidden">
            <Wordmark className="text-[26px]" />
          </a>
          <a href="#" aria-label="Arvaka, til forsiden" className="hidden group-data-[collapsible=icon]:block">
            <Monogram className="size-8 text-[22px]" />
          </a>
          <SidebarTrigger className="text-muted-foreground group-data-[collapsible=icon]:hidden" />
        </div>
        {company && (
          <p className="label truncate group-data-[collapsible=icon]:hidden" title={company}>
            {company}
          </p>
        )}
        <SidebarTrigger className="text-muted-foreground hidden group-data-[collapsible=icon]:flex" />
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  render={<a href="#ny" />}
                  tooltip="Ny samtale"
                  isActive={route === "#ny"}
                  variant="outline"
                  className="mb-2"
                >
                  <Plus />
                  <span>Ny samtale</span>
                </SidebarMenuButton>
              </SidebarMenuItem>

              {NAV.map((n) => (
                <SidebarMenuItem key={n.key}>
                  <SidebarMenuButton
                    render={<a href={n.href} />}
                    tooltip={n.label}
                    isActive={route === n.href}
                  >
                    <n.icon />
                    <span>{n.label}</span>
                  </SidebarMenuButton>
                  {n.key === "saker" && sakerCount > 0 && (
                    <SidebarMenuBadge className="bg-secondary text-foreground">
                      {sakerCount}
                    </SidebarMenuBadge>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Samtalelista finnes ikke som ikoner; sammenslått står ett ikon igjen
            som folder ut igjen. */}
        <SidebarGroup className="hidden group-data-[collapsible=icon]:block">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton tooltip="Samtaler" render={<a href="#ny" />}>
                  <MessageSquare />
                  <span>Samtaler</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {groups.map(([label, items]) => (
          <SidebarGroup key={label} className="group-data-[collapsible=icon]:hidden">
            <SidebarGroupLabel>{label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {items.map((c) => (
                  <SidebarMenuItem key={c.id} className="group/conv">
                    <SidebarMenuButton
                      render={<a href={`#c/${c.id}`} title={c.title} />}
                      isActive={c.id === activeId}
                    >
                      <span className="truncate">{c.title}</span>
                    </SidebarMenuButton>
                    <button
                      aria-label="Slett samtalen"
                      onClick={(e) => {
                        e.preventDefault()
                        onDelete(c.id)
                      }}
                      className="text-muted-foreground hover:text-foreground hover:bg-secondary absolute top-1.5 right-1.5 hidden size-6 items-center justify-center rounded-full group-hover/conv:flex group-focus-within/conv:flex"
                    >
                      <X className="size-3.5 stroke-[1.5]" />
                    </button>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}

        {!conversations.length && (
          <p className="text-muted-foreground px-4 text-[13px] leading-5 group-data-[collapsible=icon]:hidden">
            Ingen samtaler ennå. Det du spør om, blir liggende her.
          </p>
        )}
      </SidebarContent>

      <SidebarFooter className="border-sidebar-border mx-2 mb-2 border-t px-2 pt-4 group-data-[collapsible=icon]:hidden">
        <p className="text-muted-foreground text-xs leading-5">
          Leser regnskapet deres. Endrer ingenting.
        </p>
        {authEnabled() && (
          <button
            type="button"
            onClick={() => signOut(undefined, true)}
            className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-xs"
          >
            <LogOut className="size-3.5 stroke-[1.5]" /> Logg ut
          </button>
        )}
      </SidebarFooter>
    </Sidebar>
  )
}
