import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { applyTheme, getSavedTheme } from './theme'
import './style.css'

applyTheme(getSavedTheme())

createRoot(document.getElementById('enoch-dashboard-v2-root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
