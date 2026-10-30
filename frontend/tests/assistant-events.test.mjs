import test from 'node:test'
import assert from 'node:assert/strict'
import { AssistantEventDecoder, AssistantStreamError, citationPath, parseAssistantFrame } from '../src/utils/assistant-events.ts'

const id = '11111111-1111-4111-8111-111111111111'
const run = { id, conversation_id: '22222222-2222-4222-8222-222222222222', status: 'running', reason: null,
  cancel_requested: false, model_calls: 1, tool_calls: 0, cost_limit: '0.10000000', reserved: '0.09000000',
  spent: '0.01000000', budget_day: '2026-10-30', created_at: '2026-10-30T00:00:00Z', deadline_at: '2026-10-30T00:03:00Z' }
const frame = (event, data, ending = '\n') => `event: ${event}${ending}data: ${JSON.stringify(data)}${ending}${ending}`
const delta = (sequence = 1, text = '分段😀') => ({ run_id: id, sequence, text })

test('decodes fragmented UTF-8, split CRLF, comments and multiple frames in order', () => {
  const source = new TextEncoder().encode(`: heartbeat\r\n\r\n${frame('status', { run }, '\r\n')}${frame('delta', delta(), '\r\n')}${frame('delta', delta(2, '尾段'), '\r\n')}`)
  const decoder = new AssistantEventDecoder(id)
  const result = []
  for (const byte of source) result.push(...decoder.push(Uint8Array.of(byte)))
  assert.deepEqual(result.map(item => item.type), ['status', 'delta', 'delta'])
  assert.equal(result[1].text, '分段😀')
  assert.equal(result[2].sequence, 2)
})

test('does not dispatch an incomplete frame or unknown SSE extension', () => {
  const decoder = new AssistantEventDecoder(id)
  assert.deepEqual(decoder.push(new TextEncoder().encode(frame('delta', delta()).slice(0, -1))), [])
  assert.equal(decoder.push(new TextEncoder().encode('\n'))[0].type, 'delta')
  assert.equal(parseAssistantFrame(frame('future-extension', {}), id), null)
})

test('rejects malformed encodings, excessive buffers and wrong-run events', () => {
  assert.throws(() => new AssistantEventDecoder(id).push(Uint8Array.of(255)), AssistantStreamError)
  assert.throws(() => new AssistantEventDecoder(id).push(new TextEncoder().encode('a'.repeat(131073))), AssistantStreamError)
  assert.throws(() => parseAssistantFrame(frame('delta', { ...delta(), run_id: 'wrong' }), id), AssistantStreamError)
  assert.throws(() => parseAssistantFrame('event: delta\ndata: not-json\n\n', id), AssistantStreamError)
})

test('validates counters, money, sequence and completed message shape', () => {
  for (const value of [-1, 1.5, '1', null]) {
    assert.throws(() => parseAssistantFrame(frame('status', { run: { ...run, model_calls: value } }), id), AssistantStreamError)
    assert.throws(() => parseAssistantFrame(frame('delta', { ...delta(), sequence: value }), id), AssistantStreamError)
  }
  assert.throws(() => parseAssistantFrame(frame('status', { run: { ...run, spent: -1 } }), id), AssistantStreamError)
  const message = { id: 1, sequence: 2, run_id: id, role: 'assistant', content: '完成', citations: [], redacted: false, created_at: '2026-10-30T00:00:00Z' }
  assert.equal(parseAssistantFrame(frame('done', { run: { ...run, status: 'succeeded' }, message }), id).message.content, '完成')
  assert.throws(() => parseAssistantFrame(frame('done', { run, message: { ...message, role: 'user' } }), id), AssistantStreamError)
  assert.throws(() => parseAssistantFrame(frame('done', { run, message }), id), AssistantStreamError)
  assert.throws(() => parseAssistantFrame(frame('done', { run: { ...run, status: 'failed' }, message }), id), AssistantStreamError)
  assert.throws(() => parseAssistantFrame(frame('done', { run: { ...run, status: 'succeeded' }, message: null }), id), AssistantStreamError)
  assert.throws(() => parseAssistantFrame(frame('delta', delta(251)), id), AssistantStreamError)
})

test('citation destinations must exactly match server canonical relative paths', () => {
  const notice = { source_id: 'S1', kind: 'notice', item_id: 1, title: '通知', url: '/app/notices/1' }
  assert.equal(citationPath(notice), '/app/notices/1')
  for (const url of ['javascript:alert(1)', '//evil.example', '/app/notices/1?token=x', '/app/notices/2', 'https://evil.example']) {
    assert.equal(citationPath({ ...notice, url }), null)
  }
  const knowledge = { ...notice, kind: 'knowledge', version: 2, page_number: 3, url: '/api/knowledge/documents/1/source?version=2#page=3' }
  assert.equal(citationPath(knowledge), knowledge.url)
  assert.equal(citationPath({ ...knowledge, version: null }), null)
})

test('error reasons are projected to fixed safe messages and preserve authentication status', () => {
  assert.throws(() => parseAssistantFrame(frame('error', { reason: 'unauthenticated', detail: 'secret' }), id), error => error.status === 401 && !error.message.includes('secret'))
  assert.throws(() => parseAssistantFrame(frame('error', { reason: 'secret-upstream-object' }), id), error => error.status === 503 && !error.message.includes('secret'))
  assert.throws(() => parseAssistantFrame(frame('error', { reason: '__proto__' }), id), error => error.status === 503 && error.message.includes('接收连接暂不可用'))
  assert.throws(() => parseAssistantFrame(frame('error', { reason: 'expired' }), id), error => error.status === 410)
  assert.throws(() => parseAssistantFrame(frame('error', { reason: 'not_found' }), id), error => error.status === 404)
})
