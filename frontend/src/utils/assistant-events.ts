import type { AssistantEvent, AssistantMessage, AssistantRun, Citation } from '../api/assistant'

export class AssistantStreamError extends Error {
  readonly status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

const failures: Record<string, string> = {
  unauthenticated: '登录已失效，请重新登录。', unavailable: '接收连接暂不可用，可重新连接查看原运行。',
  not_found: '运行不存在或已删除。', expired: '回复已过期，请重新创建会话。', rate_limited: '连接过于频繁，请稍后重试。'
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
const count = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const amount = (value: unknown) => typeof value === 'string' && /^\d+(?:\.\d{1,8})?$/.test(value)
function validRun(value: unknown, runId: string): value is AssistantRun {
  return record(value) && value.id === runId && typeof value.conversation_id === 'string'
    && typeof value.status === 'string' && ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired'].includes(value.status)
    && typeof value.cancel_requested === 'boolean' && count(value.model_calls) && count(value.tool_calls)
    && amount(value.cost_limit) && amount(value.reserved) && amount(value.spent)
    && (value.reason === null || typeof value.reason === 'string') && typeof value.created_at === 'string'
    && typeof value.deadline_at === 'string' && typeof value.budget_day === 'string'
}

/** Canonical relative references only; model prose never becomes an href. */
export function citationPath(value: Citation): string | null {
  if (!value || !Number.isSafeInteger(value.item_id) || value.item_id < 1) return null
  const paths: Record<string, string> = { schedule: '/app/schedule', notice: `/app/notices/${value.item_id}`, activity: `/app/activities/${value.item_id}` }
  if (value.kind === 'knowledge') {
    if (!Number.isSafeInteger(value.version) || Number(value.version) < 1 || !Number.isSafeInteger(value.page_number) || Number(value.page_number) < 1) return null
    const expected = `/api/knowledge/documents/${value.item_id}/source?version=${value.version}#page=${value.page_number}`
    return value.url === expected ? expected : null
  }
  const expected = paths[value.kind]
  return typeof expected === 'string' && expected === value.url ? expected : null
}

function validMessage(value: unknown, runId: string): value is AssistantMessage {
  return record(value) && count(value.id) && Number(value.id) > 0 && count(value.sequence) && Number(value.sequence) > 0
    && value.run_id === runId && value.role === 'assistant' && typeof value.redacted === 'boolean'
    && (value.content === null || (typeof value.content === 'string' && value.content.length <= 32000))
    && typeof value.created_at === 'string' && Array.isArray(value.citations) && value.citations.length <= 99
    && value.citations.every(item => record(item) && typeof item.title === 'string'
      && typeof item.source_id === 'string' && /^S[1-9][0-9]?$/.test(item.source_id) && citationPath(item as unknown as Citation) !== null)
}

/** Pure parser shared by the browser reader and dependency-free Node tests. */
export function parseAssistantFrame(frame: string, runId: string): AssistantEvent | null {
  let kind = 'message'
  const lines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) kind = line.slice(6).trim()
    else if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''))
  }
  if (!lines.length) return null
  let value: unknown
  try { value = JSON.parse(lines.join('\n')) }
  catch { throw new AssistantStreamError('接收数据不完整，请重新连接原运行。', 502) }
  if (!record(value)) throw new AssistantStreamError('接收数据无效。', 502)
  if (kind === 'error') {
    const reason = typeof value.reason === 'string' ? value.reason : 'unavailable'
    const status: Record<string, number> = { unauthenticated: 401, not_found: 404, expired: 410, rate_limited: 429 }
    const message = Object.hasOwn(failures, reason) ? failures[reason]! : failures.unavailable!
    throw new AssistantStreamError(message, Object.hasOwn(status, reason) ? status[reason]! : 503)
  }
  if (kind === 'status' || kind === 'done') {
    if (!validRun(value.run, runId)) throw new AssistantStreamError('运行状态不匹配，请重新加载会话。', 502)
    if (kind === 'done') {
      if (!['succeeded', 'failed', 'cancelled', 'expired'].includes(value.run.status)) {
        throw new AssistantStreamError('运行尚未结束，请重新连接。', 502)
      }
      if (value.message !== null && !validMessage(value.message, runId)) throw new AssistantStreamError('回复状态不匹配，请重新加载会话。', 502)
      if (value.run.status === 'succeeded' ? !value.message || value.message.redacted || !value.message.content?.trim() : value.message !== null) {
        throw new AssistantStreamError('回复与运行终态不匹配。', 502)
      }
      return { type: 'done', run: value.run, message: value.message }
    }
    return { type: 'status', run: value.run }
  }
  if (kind === 'delta') {
    if (value.run_id !== runId || !count(value.sequence) || Number(value.sequence) < 1 || Number(value.sequence) > 250
      || typeof value.text !== 'string' || !value.text.length || value.text.length > 128) throw new AssistantStreamError('回复分段无效。', 502)
    return { type: 'delta', run_id: runId, sequence: Number(value.sequence), text: value.text }
  }
  return null
}

/** Stateful UTF-8/SSE framing; CRLF and code points may cross HTTP chunks. */
export class AssistantEventDecoder {
  private readonly runId: string
  private readonly decoder = new TextDecoder('utf-8', { fatal: true })
  private buffer = ''
  private pendingCR = false
  constructor(runId: string) { this.runId = runId }

  push(chunk: Uint8Array): AssistantEvent[] {
    let text: string
    try { text = this.decoder.decode(chunk, { stream: true }) }
    catch { throw new AssistantStreamError('回复编码无效，请重新连接。', 502) }
    if (this.pendingCR) text = '\r' + text
    this.pendingCR = text.endsWith('\r')
    if (this.pendingCR) text = text.slice(0, -1)
    this.buffer += text.replace(/\r\n|\r/g, '\n')
    if (this.buffer.length > 131072) throw new AssistantStreamError('接收数据超过允许大小。', 502)
    const events: AssistantEvent[] = []
    let boundary: number
    while ((boundary = this.buffer.indexOf('\n\n')) >= 0) {
      const frame = this.buffer.slice(0, boundary)
      this.buffer = this.buffer.slice(boundary + 2)
      const event = parseAssistantFrame(frame, this.runId)
      if (event) events.push(event)
    }
    return events
  }
}
