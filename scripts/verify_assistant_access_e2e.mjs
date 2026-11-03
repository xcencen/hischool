/** Actual Nginx consent withdrawal and SSE revocation, synthetic accounts only. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { randomUUID } from 'node:crypto'

const args = Object.fromEntries(process.argv.slice(2).reduce((r, v, i, a) => {
  if (v.startsWith('--')) r.push([v.slice(2), a[i + 1]])
  return r
}, []))
assert(args.artifacts && args.origin)
const origin = new URL(args.origin).origin
assert(['127.0.0.1', 'localhost'].includes(new URL(origin).hostname))
const folder = path.resolve(args.artifacts)
const manifest = JSON.parse(await fs.readFile(path.join(folder, 'ready.json'), 'utf8'))
assert.equal(manifest.synthetic_only, true)
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
let token
async function request(url, method = 'GET', body, expected) {
  for (let attempt = 0; ; attempt++) {
    const response = await fetch(origin + '/api' + url, { method,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000) })
    if (response.status === 429 && body?.request_key && attempt < 9) {
      await response.body?.cancel(); await sleep(6000); continue
    }
    if (expected === undefined) assert(response.ok, `${method} ${url}: ${response.status}`)
    else assert.equal(response.status, expected, `${method} ${url}`)
    return (await response.json()).data
  }
}
const report = { synthetic_only: true, passed: false, checks: [] }
try {
  token = (await request('/auth/login', 'POST', { username: manifest.username, password: manifest.password })).token
  await request('/admin/assistant/operations', 'GET', undefined, 403)
  report.checks.push('ordinary account cannot read global operations')
  const access = await request('/assistant/access')
  assert.equal(access.can_run, true)
  const conversation = await request('/assistant/conversations', 'POST', { title: 'M6 synthetic withdrawal' })
  const run = await request(`/assistant/conversations/${conversation.id}/runs`, 'POST',
    { content: '__m5_ops_long__', request_key: randomUUID() })
  for (let attempt = 0; ; attempt++) {
    const detail = await request(`/assistant/runs/${run.id}`)
    if (detail.status === 'running' && detail.model_calls === 1) break
    assert(attempt < 100, 'Model dispatch must begin before withdrawal')
    await sleep(100)
  }
  const stream = await fetch(`${origin}/api/assistant/runs/${run.id}/events`, {
    headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15000) })
  assert.equal(stream.status, 200)
  const withdrawn = await request('/assistant/consent', 'DELETE')
  assert.equal(withdrawn.can_run, false)
  const frames = await stream.text()
  assert.match(frames, /^event: error/m)
  assert.doesNotMatch(frames, /^event: (?:delta|done)/m)
  const reconnect = await fetch(`${origin}/api/assistant/runs/${run.id}/events`, {
    headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5000) })
  assert.equal(reconnect.status, 403)
  await reconnect.body?.cancel()
  let final
  for (let attempt = 0; ; attempt++) {
    final = await request(`/assistant/runs/${run.id}`)
    if (!['queued', 'running'].includes(final.status)) break
    assert(attempt < 100, 'Revoked execution must settle')
    await sleep(100)
  }
  assert.equal(final.reason, 'access_revoked')
  assert.equal(final.model_calls, 1)
  assert.equal(Number(final.reserved), 0)
  assert(final.usage.every(item => item.state !== 'reserved'))
  assert.equal((await request(`/assistant/conversations/${conversation.id}/messages`)).list.filter(item => item.role === 'assistant').length, 0)
  report.checks.push('withdrawal closes active SSE without answer', 'revoked reconnect denied',
    'in-flight request settled once with no reservation or persisted answer')
  const before = await request('/assistant/budget')
  await request(`/assistant/conversations/${conversation.id}/runs`, 'POST',
    { content: 'Must not dispatch', request_key: randomUUID() }, 403)
  const after = await request('/assistant/budget')
  assert.equal(after.user.reserved, before.user.reserved)
  assert.equal(after.user.spent, before.user.spent)
  await request('/user/me')
  await request('/assistant/consent', 'POST', { policy_version: access.policy.version })
  const old = await fetch(`${origin}/api/assistant/runs/${run.id}/events`, {
    headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5000) })
  assert.equal(old.status, 403)
  await old.body?.cancel()
  assert.equal((await request(`/assistant/runs/${run.id}`)).spent, final.spent)
  report.checks.push('denied submit adds no reserve or charge and keeps campus login',
    'new consent cannot revive old run or duplicate charge')
  report.passed = true
} finally {
  await fs.writeFile(path.join(folder, 'access-results.json'), JSON.stringify(report, null, 2))
}
console.log(JSON.stringify(report))
