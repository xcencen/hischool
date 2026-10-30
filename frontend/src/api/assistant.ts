import { ApiError, request } from '../utils/campus-request'
import { readToken, storeToken } from '../utils/session-storage'
import { AssistantEventDecoder, AssistantStreamError } from '../utils/assistant-events'

export interface AssistantPage<T> { list: T[]; total: number; page: number; page_size: number }
export interface Conversation {
  id: string; title: string; state: 'active' | 'archived' | 'expired' | 'deleted'
  active_run_id: string | null; created_at: string; updated_at: string; expires_at: string
}
export interface Citation {
  source_id: string; kind: 'notice' | 'activity' | 'schedule' | 'knowledge'; item_id: number
  title: string; url: string; version?: number | null; page_number?: number | null
  page_label?: string | null; chapter?: string | null; chunk_id?: number | null
}
export interface AssistantMessage {
  id: number; sequence: number; run_id: string | null; role: 'user' | 'assistant'
  content: string | null; citations: Citation[]; redacted: boolean; created_at: string
}
export interface AssistantRun {
  id: string; conversation_id: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'expired'
  reason: string | null; cancel_requested: boolean; model_calls: number; tool_calls: number
  cost_limit: string; reserved: string; spent: string; budget_day: string
  created_at: string; started_at: string | null; finished_at: string | null; deadline_at: string
}
export interface AssistantBudget {
  day: string; currency: 'CNY'
  user: { cap: string; spent: string; reserved: string; available: string; estimated: boolean }
  policy: { enabled: boolean; allow_campus_data: boolean; run_cost_limit: string; alert_ratio: string; retention_days: number }
}
export type AssistantEvent = { type: 'status'; run: AssistantRun }
  | { type: 'delta'; run_id: string; sequence: number; text: string }
  | { type: 'done'; run: AssistantRun; message: AssistantMessage | null }

export const conversationsApi = (page = 1, signal?: AbortSignal) =>
  request<AssistantPage<Conversation>>({ url: '/assistant/conversations', params: { page, page_size: 30 }, signal })
export const conversationApi = (id: string, signal?: AbortSignal) =>
  request<Conversation>({ url: `/assistant/conversations/${id}`, signal })
export const createConversationApi = (signal?: AbortSignal) =>
  request<Conversation>({ method: 'POST', url: '/assistant/conversations', data: { title: '新会话' }, signal })
export const updateConversationApi = (id: string, state: 'active' | 'archived', signal?: AbortSignal) =>
  request<Conversation>({ method: 'PATCH', url: `/assistant/conversations/${id}`, data: { state }, signal })
export const deleteConversationApi = (id: string, signal?: AbortSignal) =>
  request<{ id: string; state: string }>({ method: 'DELETE', url: `/assistant/conversations/${id}`, signal })
export const messagesApi = (id: string, page = 1, signal?: AbortSignal) =>
  request<AssistantPage<AssistantMessage>>({ url: `/assistant/conversations/${id}/messages`, params: { page, page_size: 50 }, signal })
export const getRunApi = (id: string, signal?: AbortSignal) =>
  request<AssistantRun>({ url: `/assistant/runs/${id}`, signal })
export const createRunApi = (id: string, content: string, key: string, signal?: AbortSignal) =>
  request<AssistantRun>({ method: 'POST', url: `/assistant/conversations/${id}/runs`, data: { content, request_key: key }, signal })
export const cancelRunApi = (id: string, signal?: AbortSignal) =>
  request<AssistantRun>({ method: 'POST', url: `/assistant/runs/${id}/cancel`, signal })
export const assistantBudgetApi = (signal?: AbortSignal) => request<AssistantBudget>({ url: '/assistant/budget', signal })

const failures: Record<string, string> = {
  unauthenticated: '登录已失效，请重新登录。', unavailable: '接收连接暂不可用，可重新连接查看原运行。',
  not_found: '运行不存在或已删除。', expired: '回复已过期，请重新创建会话。', rate_limited: '连接过于频繁，请稍后重试。'
}

function failSession(current: string) {
  if (current && current === readToken()) {
    storeToken('')
    window.dispatchEvent(new Event('campus:session-expired'))
  }
}

/** A subscription only: disconnecting never cancels or resubmits model work. */
export async function subscribeRun(id: string, onEvent: (event: AssistantEvent) => void, signal: AbortSignal): Promise<void> {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
  const current = readToken()
  if (!current) throw new ApiError('请先登录。', 401)
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal.addEventListener('abort', abort, { once: true })
  if (signal.aborted) controller.abort()
  let deadline = 0
  const renew = () => { window.clearTimeout(deadline); deadline = window.setTimeout(abort, 25000) }
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  let done = false
  try {
    renew()
    const response = await fetch(`${base}/api/assistant/runs/${encodeURIComponent(id)}/events?after=0`, {
      headers: { Authorization: `Bearer ${current}`, Accept: 'text/event-stream' }, cache: 'no-store',
      credentials: 'omit', redirect: 'error', signal: controller.signal
    })
    if (!response.ok) {
      if (response.status === 401) failSession(current)
      const message = response.status === 404 ? failures.not_found! : response.status === 410 ? failures.expired! : response.status === 429 ? failures.rate_limited! : failures.unavailable!
      throw new ApiError(message, response.status)
    }
    if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
      throw new ApiError('服务未返回流式响应，请稍后重新连接。', 502)
    }
    reader = response.body.getReader()
    const decoder = new AssistantEventDecoder(id)
    while (!done) {
      const part = await reader.read()
      if (part.done) break
      if (current !== readToken() || signal.aborted) throw new DOMException('Session changed', 'AbortError')
      renew()
      for (const event of decoder.push(part.value)) {
        onEvent(event)
        if (event.type === 'done') { done = true; break }
      }
    }
    if (!done) throw new ApiError('连接已中断。可重新连接查看同一次运行，不会再次提交问题。', 0)
  } catch (error) {
    if (signal.aborted) throw error
    if (error instanceof AssistantStreamError) {
      if (error.status === 401) failSession(current)
      throw new ApiError(error.message, error.status)
    }
    if (error instanceof ApiError) {
      if (error.status === 401) failSession(current)
      throw error
    }
    throw new ApiError(controller.signal.aborted ? '接收等待超时，请重新连接原运行。' : '连接已中断，请重新连接原运行。', 0)
  } finally {
    window.clearTimeout(deadline)
    signal.removeEventListener('abort', abort)
    await reader?.cancel().catch(() => {})
    reader?.releaseLock()
  }
}
