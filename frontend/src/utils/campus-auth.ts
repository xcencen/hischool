import { ref, shallowRef } from 'vue'
import type { CampusUser, Credentials, Role } from '../api/campus'
import { currentUserApi, loginApi, logoutApi } from '../api/campus'
import { ApiError } from './campus-request'
import { readToken, storeToken, tokenStorageKey } from './session-storage'

export const token = ref(readToken())
export const user = shallowRef<CampusUser | null>(null)
let pendingUser: Promise<CampusUser> | null = null
let pendingToken = ''

export function clearSession(): void {
  storeToken('')
  token.value = ''
  user.value = null
}

export function saveUser(value: CampusUser): void {
  user.value = value
}

export async function loadCurrentUser(force = false): Promise<CampusUser> {
  if (!token.value) throw new ApiError('请先登录。', 401)
  if (!force && user.value) return user.value
  if (pendingUser && pendingToken === token.value) return pendingUser
  const expectedToken = token.value
  const currentRequest = currentUserApi().then(value => {
    if (token.value !== expectedToken) throw new ApiError('登录状态已变化，请重新打开页面。', 401)
    saveUser(value)
    return value
  }).finally(() => {
    if (pendingUser === currentRequest) { pendingUser = null; pendingToken = '' }
  })
  pendingUser = currentRequest
  pendingToken = expectedToken
  return currentRequest
}

export async function login(credentials: Credentials): Promise<CampusUser> {
  const result = await loginApi(credentials)
  storeToken(result.token)
  token.value = result.token
  saveUser(result.user)
  return result.user
}

export async function logout(): Promise<void> {
  try {
    await logoutApi()
  } finally {
    clearSession()
  }
}

export function roleLabel(role: Role | undefined): string {
  return role ? { student: '学生', teacher: '教师', admin: '管理员' }[role] : '未登录'
}

export function safeRedirect(value: unknown): string {
  if (typeof value === 'string' && (/^\/app(?:\/|$|\?)/.test(value) || /^\/admin(?:\/|$|\?)/.test(value))) {
    return value
  }
  return '/app'
}

window.addEventListener('campus:session-expired', clearSession)
window.addEventListener('storage', event => {
  if (event.key === tokenStorageKey) {
    token.value = readToken()
    user.value = null
  }
})
