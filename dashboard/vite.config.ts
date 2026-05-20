import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/control/dashboard-v2/',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../enoch_control_plane/control_plane/dashboard_v2',
    emptyOutDir: true,
    assetsDir: 'assets',
  },
})
