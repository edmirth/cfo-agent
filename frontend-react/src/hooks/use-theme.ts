import { useEffect } from "react"

/** Følger systemets fargemodus; shadcn bytter på .dark. */
export function useTheme() {
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const on = () => document.documentElement.classList.toggle("dark", mq.matches)
    on()
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
}
