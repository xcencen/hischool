const key = 'campus_token'

export function readToken(): string {
  return localStorage.getItem(key) ?? ''
}

export function storeToken(value: string): void {
  if (value) localStorage.setItem(key, value)
  else localStorage.removeItem(key)
}

export const tokenStorageKey = key
