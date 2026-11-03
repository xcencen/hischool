/** Only the disposable M5 stack; actual proxy, Redis interruption, no cloud. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { randomUUID } from 'node:crypto'
const execute = promisify(execFile)
const args = Object.fromEntries(process.argv.slice(2).reduce((r, v, i, a) => {
  if (v.startsWith('--')) r.push([v.slice(2), a[i + 1]])
  return r
}, []))
assert(args.artifacts && args.project && args.docker && args.origin)
assert.match(args.project, /^my-campus-ai-m6-e2e(?:-[a-z0-9-]+)?$/)
const folder = args.artifacts
const origin = new URL('/api', args.origin).href
assert(['127.0.0.1', 'localhost'].includes(new URL(origin).hostname))
const container = `${args.project}-test-redis-1`
const docker = args.docker
const inspected = JSON.parse((await execute(docker, ['container', 'inspect', container], { timeout: 15000 })).stdout)[0]
assert.equal(inspected.Config.Labels['com.docker.compose.project'], args.project)
assert.equal(inspected.Config.Labels['com.docker.compose.service'], 'test-redis')
const manifest = JSON.parse(await fs.readFile(`${folder}/ready.json`, 'utf8'))
assert.equal(manifest.synthetic_only, true)
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
let token
async function api(path, body) {
  for (let attempt = 0; attempt < 10; attempt++) {
    const response = await fetch(origin + path, { method: body ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000) })
    if (response.status === 429 && body?.request_key && attempt < 9) { await response.body?.cancel(); await sleep(6000); continue }
    assert(response.ok, `${path}: HTTP ${response.status}`)
    return (await response.json()).data
  }
}
async function run(query) {
  const conversation = await api('/assistant/conversations', { title: 'M5 operations synthetic' })
  return api(`/assistant/conversations/${conversation.id}/runs`, { content: query, request_key: randomUUID() })
}
async function connect(id) {
  const started = performance.now()
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 65000)
  const response = await fetch(`${origin}/assistant/runs/${id}/events`, {
    headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
  return { response, started, close: async () => { clearTimeout(timeout); controller.abort(); await response.body?.cancel().catch(() => {}) }, timeout }
}
async function consume(connection, delay = 0) {
  assert.equal(connection.response.status, 200)
  const start = performance.now(), events = []
  let buffer = '', heartbeats = 0, firstStatusMs = null
  const decoder = new TextDecoder()
  try {
    for await (const part of connection.response.body) {
      buffer += decoder.decode(part, { stream: true })
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
        if (frame.startsWith(': heartbeat')) heartbeats++
        const event = frame.match(/^event: (.+)$/m)?.[1], data = frame.match(/^data: (.+)$/m)?.[1]
        if (event && data) {
          if (event === 'status' && firstStatusMs === null) firstStatusMs = performance.now() - connection.started
          events.push({ event, data: JSON.parse(data) })
        }
      }
      if (delay) await sleep(delay)
    }
  } finally { clearTimeout(connection.timeout) }
  return { events, heartbeats, firstStatusMs, elapsedMs: performance.now() - start }
}
const report = { synthetic_only: true, checks: [], metrics: {} }
try {
  token = (await api('/auth/login', { username: manifest.username, password: manifest.password })).token
  const long = await run('__m5_ops_long__')
  const first = await connect(long.id), second = await connect(long.id)
  try {
    assert.equal(first.response.status, 200); assert.equal(second.response.status, 200)
    const denied = await connect(long.id)
    try { assert.equal(denied.response.status, 429) } finally { await denied.close() }
    const [a, b] = await Promise.all([consume(first), consume(second)])
    assert(a.heartbeats >= 1 && b.heartbeats >= 1, 'Long running streams must have real 10s heartbeats')
    assert(a.events.some(e => e.event === 'done' && e.data.run.status === 'succeeded'))
    assert.equal((await api(`/assistant/runs/${long.id}`)).model_calls, 1)
    report.checks.push('HTTP per-user 2 subscriptions; third 429', 'real 10s heartbeat', 'two subscriptions invoke model once')
    report.metrics.longStreamMs = a.elapsedMs
    report.metrics.longFirstStatusMs = a.firstStatusMs
  } finally { await first.close(); await second.close() }
  const large = await run('__m5_ops_large__')
  const slow = await consume(await connect(large.id), 100)
  const terminal = slow.events.find(e => e.event === 'done')?.data
  assert.equal(terminal?.run.status, 'succeeded')
  assert.equal(slow.events.filter(e => e.event === 'delta').map(e => e.data.text).join(''), terminal.message.content)
  report.checks.push('slow reader receives exact authoritative complete answer')
  report.metrics.slowStreamMs = slow.elapsedMs
  const fault = await run('__m5_ops_fault__')
  let dispatched = false
  for (let attempt = 0; attempt < 100; attempt++) {
    const current = await api(`/assistant/runs/${fault.id}`)
    if (current.status === 'running' && current.model_calls === 1) { dispatched = true; break }
    await sleep(100)
  }
  assert(dispatched, 'Fault must interrupt a dispatched model, not merely a queued run')
  const connection = await connect(fault.id)
  assert.equal(connection.response.status, 200)
  const reading = consume(connection).then(value => ({ value }), error => ({ error }))
  let pauseAttempted = false
  try {
    pauseAttempted = true
    await execute(docker, ['pause', container], { timeout: 15000 })
    // Cover the 10s heartbeat and the enclosing 10s SQL/identity deadline,
    // including Redis client retry behavior, before the 30s synthetic reply.
    await sleep(22500)
  } finally {
    if (pauseAttempted) await execute(docker, ['unpause', container], { timeout: 15000 })
  }
  const outcome = await reading
  if (outcome.error) throw outcome.error
  const failed = outcome.value
  assert(failed.events.some(e => e.event === 'error' && e.data.reason === 'unavailable'))
  assert(!failed.events.some(e => e.event === 'delta'), 'Never emit unverified text during Redis failure')
  let final
  const started = performance.now()
  while (performance.now() - started < 60000) {
    final = await api(`/assistant/runs/${fault.id}`)
    if (['failed', 'cancelled', 'expired'].includes(final.status)) break
    await sleep(1000)
  }
  report.faultStatus = final.status
  assert(['failed', 'cancelled', 'expired'].includes(final.status), 'Interrupted run must reach terminal state')
  assert.equal(Number(final.reserved), 0)
  assert.equal(final.model_calls, 1, 'Failure recovery must not replay model work')
  report.checks.push('actual Redis pause: fail closed with no answer', 'restore Redis: terminal recovery, no replay, reservation released')
  report.metrics.recoveryAfterRestoreMs = performance.now() - started
  report.faultReason = final.reason
  const cancellation = await run('__m5_ops_long__')
  for (let attempt = 0; attempt < 100; attempt++) {
    if ((await api(`/assistant/runs/${cancellation.id}`)).model_calls === 1) break
    await sleep(100)
  }
  const cancelStarted = performance.now()
  await api(`/assistant/runs/${cancellation.id}/cancel`, {})
  let cancelled
  for (let attempt = 0; attempt < 30; attempt++) {
    cancelled = await api(`/assistant/runs/${cancellation.id}`)
    if (['cancelled', 'failed'].includes(cancelled.status)) break
    await sleep(1000)
  }
  assert.equal(cancelled.status, 'cancelled')
  assert.equal(Number(cancelled.reserved), 0)
  assert.equal(cancelled.model_calls, 1)
  report.checks.push('actual in-flight cancellation: terminal and reservation released')
  report.metrics.cancellationMs = performance.now() - cancelStarted
  report.passed = true
} catch (error) { report.passed = false; report.error = error.message; throw error }
finally { await fs.writeFile(`${folder}/operations-results.json`, JSON.stringify(report, null, 2)); console.log(JSON.stringify(report)) }
