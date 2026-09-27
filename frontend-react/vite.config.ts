import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  // Dev-serveren snakker med FastAPI-en som allerede kjører.
  server: { proxy: { "/api": process.env.CFO_API || "http://localhost:8000" } },
  // Bygget legges der FastAPI kan serve det.
  build: { outDir: "dist", emptyOutDir: true },
})
