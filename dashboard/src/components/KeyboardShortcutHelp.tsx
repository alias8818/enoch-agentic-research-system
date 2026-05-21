import { DASHBOARD_KEYBOARD_SHORTCUTS, type KeyboardShortcutScope } from '../keyboardShortcuts'

function scopeLabel(scope: KeyboardShortcutScope): string {
  return scope === 'global' ? 'Global' : 'Tables'
}

export function KeyboardShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null

  const grouped = DASHBOARD_KEYBOARD_SHORTCUTS.reduce<Record<KeyboardShortcutScope, typeof DASHBOARD_KEYBOARD_SHORTCUTS>>((acc, shortcut) => {
    acc[shortcut.scope].push(shortcut)
    return acc
  }, { global: [], table: [] })

  return (
    <dialog className="keyboard-help-dialog" open aria-labelledby="keyboard-help-title" aria-modal="true">
      <div className="keyboard-help-card">
        <div className="keyboard-help-header">
          <div>
            <p className="eyebrow">Operator chrome</p>
            <h2 id="keyboard-help-title">Keyboard shortcuts</h2>
            <p className="keyboard-help-lead">Shortcuts are disabled while typing in form fields.</p>
          </div>
          <button className="secondary-button" type="button" onClick={onClose} autoFocus>Close</button>
        </div>
        {(['global', 'table'] as const).map((scope) => (
          <section key={scope} className="keyboard-help-section" aria-label={`${scopeLabel(scope)} shortcuts`}>
            <h3>{scopeLabel(scope)}</h3>
            <dl className="keyboard-help-list">
              {grouped[scope].map((shortcut) => (
                <div key={shortcut.keys} className="keyboard-help-row">
                  <dt><kbd>{shortcut.keys}</kbd></dt>
                  <dd>{shortcut.description}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </dialog>
  )
}
