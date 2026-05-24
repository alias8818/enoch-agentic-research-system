import '@testing-library/jest-dom/vitest'

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>()

  get length(): number {
    return this.values.size
  }

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.has(key) ? this.values.get(key)! : null
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    this.values.set(key, String(value))
  }
}

function hasStorageApi(value: unknown): value is Storage {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Storage).getItem === 'function' &&
    typeof (value as Storage).setItem === 'function' &&
    typeof (value as Storage).removeItem === 'function'
  )
}

const storage = hasStorageApi(globalThis.window?.localStorage)
  ? globalThis.window.localStorage
  : new MemoryStorage()

Object.defineProperty(globalThis.window, 'localStorage', {
  configurable: true,
  value: storage,
})
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: storage,
})
