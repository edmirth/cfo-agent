import { BarChart3, Building2, ListFilter, LogOut, MessageSquare, Plus } from "lucide-react"

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
  { href: "#", key: "home", label: "Brief", icon: BarChart3 },
  { href: "#saker", key: "saker", label: "Saker", icon: ListFilter },
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
    <Sidebar collapsible="icon" variant="floating">
      <SidebarHeader>
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-md text-[10px] font-bold tracking-wide">
            CFO
          </span>
          <span className="truncate text-sm font-semibold group-data-[collapsible=icon]:hidden">
            {company}
          </span>
          <SidebarTrigger className="ml-auto group-data-[collapsible=icon]:hidden" />
        </div>
        <SidebarTrigger className="hidden group-data-[collapsible=icon]:flex" />
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
                  className="border"
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
                    <SidebarMenuBadge className="bg-destructive text-white">
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
                      className="text-muted-foreground hover:text-destructive absolute top-1 right-1 hidden size-6 items-center justify-center rounded-sm group-hover/conv:flex"
                    >
                      ×
                    </button>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}

        {!conversations.length && (
          <p className="text-muted-foreground px-4 text-xs leading-relaxed group-data-[collapsible=icon]:hidden">
            Ingen samtaler ennå. Det du spør om, blir liggende her.
          </p>
        )}
      </SidebarContent>

      <SidebarFooter className="group-data-[collapsible=icon]:hidden">
        <p className="text-muted-foreground px-2 text-[11px]">
          Leser regnskapet deres. Endrer ingenting.
        </p>
        {authEnabled() && (
          <button
            type="button"
            onClick={() => signOut(undefined, true)}
            className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 px-2 text-[11px]"
          >
            <LogOut className="size-3" /> Logg ut
          </button>
        )}
      </SidebarFooter>
    </Sidebar>
  )
}
