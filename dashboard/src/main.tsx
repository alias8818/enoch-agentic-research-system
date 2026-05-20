import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './style.css'

createRoot(document.getElementById('enoch-dashboard-v2-root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
