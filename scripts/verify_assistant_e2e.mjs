/** Actual isolated proxy/API/queue/worker/MCP acceptance. No intercepted API. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'
import { randomUUID } from 'node:crypto'

const args = Object.fromEntries(process.argv.slice(2).reduce((r, v, i, a) => {
  if (v.startsWith('--')) r.push([v.slice(2), a[i + 1]])
  return r
}, []))
assert(args.artifacts && args.playwright && args.browser)
const origin = 'http://127.0.0.1:18765'
const folder = path.resolve(args.artifacts)
process.env.TEMP = process.env.TMP = process.env.TMPDIR = folder
const manifest = JSON.parse(await fs.readFile(path.join(folder, 'ready.json'), 'utf8'))
assert.equal(manifest.synthetic_only, true)
const cases = JSON.parse(await fs.readFile(new URL('../backend/tests/fixtures/assistant_cases.json', import.meta.url), 'utf8'))
const { chromium } = createRequire(import.meta.url)(args.playwright)
const results = []
const browser = await chromium.launch({ executablePath: args.browser, headless: true })
const context = await browser.newContext()
context.setDefaultTimeout(15000)
context.setDefaultNavigationTimeout(20000)
const errors = []
const responses = []
// Block external traffic, while leaving every local API and SSE request real.
await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
const page = await context.newPage()
page.setDefaultTimeout(15000)
page.setDefaultNavigationTimeout(20000)
page.on('pageerror', error => errors.push(error.message))
page.on('response', response => {
  const url = new URL(response.url())
  if (url.pathname.startsWith('/api/')) responses.push({ path: url.pathname, status: response.status() })
})
function phase(name, detail = {}) { console.log(JSON.stringify({ phase: name, ...detail })) }
async function api(url, { token, method = 'GET', body } = {}) {
  for (let attempt = 0; attempt < 10; attempt++) {
    const response = await fetch(origin + '/api' + url, { method,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(30000) })
    const result = await response.json()
    // Only a definitive admission denial is retried, with the SAME request key.
    // Network/5xx ambiguity must fail; production admission limits stay enabled.
    if (response.status === 429 && method === 'POST' && /\/conversations\/[^/]+\/runs$/.test(url) && attempt < 9) {
      const retry = response.headers.get('retry-after')
      const seconds = retry ? (/^\d+(?:\.\d+)?$/.test(retry) ? Number(retry) : (Date.parse(retry) - Date.now()) / 1000) : 6
      assert(Number.isFinite(seconds) && seconds >= 0 && seconds <= 30, 'Unsupported Retry-After; stop acceptance')
      console.log(JSON.stringify({ status: 'admission_rate_limited', retrySeconds: Math.max(1, seconds), attempt: attempt + 1 }))
      await new Promise(resolve => setTimeout(resolve, Math.max(1, seconds) * 1000))
      continue
    }
    assert.equal(response.ok, true, `${method} ${url}: ${response.status} ${result.message}`)
    return result.data
  }
}
async function stream(runId, token) {
  const start = performance.now()
  const response = await fetch(`${origin}/api/assistant/runs/${runId}/events?after=0`, {
    headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(30000) })
  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-type'), /text\/event-stream/)
  assert.match(response.headers.get('cache-control'), /no-store/)
  const events = []
  let buffer = '', firstMs
  const decoder = new TextDecoder()
  for await (const bytes of response.body) {
    buffer += decoder.decode(bytes, { stream: true }).replaceAll('\r\n', '\n')
    let at
    while ((at = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, at); buffer = buffer.slice(at + 2)
      const event = frame.match(/^event:\s*(.+)$/m)?.[1]
      const data = frame.match(/^data:\s*(.+)$/m)?.[1]
      if (event && data) {
        firstMs ??= performance.now() - start
        events.push({ event, data: JSON.parse(data) })
      }
    }
  }
  const done = events.find(e => e.event === 'done')?.data
  if (!done) {
    const diagnostic = { run: await api(`/assistant/runs/${runId}`, { token }),
      events: events.map(e => ({ event: e.event, reason: e.data.reason, status: e.data.run?.status })),
      firstMs, totalMs: performance.now() - start, trailingBytes: buffer.length }
    await fs.writeFile(path.join(folder, 'stream-failure.json'), JSON.stringify(diagnostic, null, 2))
    assert.fail('SSE did not deliver a terminal event through Nginx: ' + JSON.stringify(diagnostic.events))
  }
  assert.equal(done.run.status, 'succeeded', done.run.reason)
  assert.equal(events.filter(e => e.event === 'delta').map(e => e.data.text).join(''), done.message.content)
  return { done, events, firstMs, totalMs: performance.now() - start }
}
try {
  const login = await api('/auth/login', { method: 'POST', body: { username: manifest.username, password: manifest.password } })
  const token = login.token
  const baseline = await api('/assistant/budget', { token })
  const conversation = await api('/assistant/conversations', { token, method: 'POST', body: { title: 'M5 actual chain' } })
  for (const fixture of cases) {
    const body = { content: fixture.query, request_key: randomUUID() }
    const run = await api(`/assistant/conversations/${conversation.id}/runs`, { token, method: 'POST', body })
    const replay = await api(`/assistant/conversations/${conversation.id}/runs`, { token, method: 'POST', body })
    assert.equal(replay.id, run.id, 'Idempotent submit created another run')
    const received = await stream(run.id, token)
    const detail = await api(`/assistant/runs/${run.id}`, { token })
    const message = received.done.message
    const evidence = fixture.tool ? JSON.parse(message.content.replace(/^合成证据：/, '').replace(/\[S\d+\]/g, '').trim()) : null
    assert.equal(detail.tool_calls, fixture.tool ? 1 : 0)
    assert.equal(detail.model_calls, fixture.tool ? 2 : 1)
    assert.equal(Number(detail.reserved), 0)
    assert(Number(detail.spent) > 0)
    assert.equal(detail.usage.length, detail.model_calls + detail.tool_calls)
    assert(detail.usage.every(u => u.state === (u.kind === 'embedding' ? 'unknown' : 'settled')))
    const sum = detail.usage.reduce((n, u) => n + Number(u.charged), 0)
    assert(Math.abs(sum - Number(detail.spent)) < 1e-8)
    assert(!/private-person|private-phone|private-review|private@example|password-hash/.test(message.content))
    if (fixture.id === 'today') {
      assert(message.content.includes(manifest.course_a))
      assert(!message.content.includes(manifest.course_b))
      assert(message.content.includes('test-a'))
    }
    if (fixture.id === 'tomorrow') assert(message.content.includes('"items": []'))
    if (fixture.id === 'week') {
      assert(evidence.items.some(item => item.course_name === manifest.course_a && item.location === 'test-a'))
      assert(evidence.items.every(item => item.course_name !== manifest.course_b))
      assert(message.citations.some(c => c.kind === 'schedule' && c.url === '/app/schedule'))
    }
    if (fixture.id === 'notices') {
      assert(evidence.items.some(item => item.id === manifest.notice_id && item.content.startsWith('Public notice ')))
      assert(evidence.items.every(item => ![manifest.draft_notice_id, manifest.hidden_notice_id].includes(item.id)))
      assert(message.citations.some(c => c.item_id === manifest.notice_id && c.url === `/app/notices/${manifest.notice_id}`))
    }
    if (fixture.id === 'notice') {
      assert.equal(evidence.id, manifest.notice_id)
      assert(evidence.content.startsWith('Public notice '))
      assert(message.citations.some(c => c.item_id === manifest.notice_id && c.kind === 'notice'))
    }
    if (fixture.id === 'activities') {
      assert(evidence.items.some(item => item.id === manifest.activity_id && item.location === 'test'))
      assert(evidence.items.every(item => item.id !== manifest.draft_activity_id && !Object.hasOwn(item, 'registration_status')))
      assert(message.citations.some(c => c.item_id === manifest.activity_id && c.url === `/app/activities/${manifest.activity_id}`))
    }
    if (fixture.id === 'activity') {
      assert.equal(evidence.registration_status, 'registered')
      assert.equal(evidence.id, manifest.activity_id)
      assert.equal(evidence.content, 'Public activity')
    }
    if (fixture.id === 'handbook') {
      assert(message.content.includes('Scholarship applicants submit complete materials.'))
      const citation = message.citations.find(c => c.kind === 'knowledge')
      assert.equal(citation.item_id, manifest.document_id)
      assert.equal(citation.version, manifest.version)
      assert.equal(citation.page_number, 1)
      assert(citation.chunk_id > 0)
      assert.equal(citation.url, `/api/knowledge/documents/${manifest.document_id}/source?version=${manifest.version}#page=1`)
    }
    if (!fixture.tool) {
      assert.equal(message.citations.length, 0)
      assert(message.content.includes({ write: '不能执行报名', identity: '不能指定他人身份', missing: '提供活动编号', injection: '不能提供系统提示和密钥' }[fixture.id]))
    }
    // Re-subscribe and confirm no tool/model is repeated or charged twice.
    await stream(run.id, token)
    const after = await api(`/assistant/runs/${run.id}`, { token })
    assert.equal(after.spent, detail.spent)
    assert.equal(after.model_calls, detail.model_calls)
    results.push({ id: fixture.id, runId: run.id, tool: fixture.tool, status: detail.status, firstMs: received.firstMs,
      totalMs: received.totalMs, spent: detail.spent, citations: message.citations.length })
    console.log(JSON.stringify({ case: fixture.id, status: detail.status, toolCalls: detail.tool_calls }))
  }
  const history = await api(`/assistant/conversations/${conversation.id}/messages?page_size=100`, { token })
  assert.equal(history.total, cases.length * 2)
  const budget = await api('/assistant/budget', { token })
  assert.equal(Number(budget.user.reserved), 0)
  const total = results.reduce((n, r) => n + Number(r.spent), 0)
  assert(Math.abs(Number(budget.user.spent) - Number(baseline.user.spent) - total) < 1e-8)
  const other = await api('/auth/login', { method: 'POST', body: { username: manifest.other_username, password: manifest.password } })
  const forbidden = await fetch(`${origin}/api/assistant/conversations/${conversation.id}/messages`, { headers: { Authorization: `Bearer ${other.token}` } })
  assert.equal(forbidden.status, 404)
  await fs.writeFile(path.join(folder, 'api-results.json'), JSON.stringify(results, null, 2))

  // Real login form, production bundle, two submitted rounds and history reload.
  // Leave two real admission tokens for the two UI sends; the UI does not retry 429.
  console.log(JSON.stringify({ status: 'browser_admission_refill', waitSeconds: 13 }))
  await new Promise(resolve => setTimeout(resolve, 13000))
  phase('browser_login')
  await page.goto(origin + '/login?redirect=/app/assistant')
  await page.getByPlaceholder('请输入账号').fill(manifest.username)
  await page.getByPlaceholder('请输入密码').fill(manifest.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/app/assistant')
  phase('browser_new_conversation')
  await page.getByRole('button', { name: '＋ 新建' }).click()
  await page.getByRole('heading', { name: '开始一段校园对话' }).waitFor()
  for (const fixture of cases.slice(0, 2)) {
    phase('browser_send', { case: fixture.id })
    await page.locator('#assistant-input').fill(fixture.query)
    const [terminal, submittedResponse] = await Promise.all([
      page.waitForResponse(r => r.url().includes('/events?') && r.status() === 200),
      page.waitForResponse(r => r.request().method() === 'POST' && /\/assistant\/conversations\/[^/]+\/runs$/.test(new URL(r.url()).pathname)),
      page.getByRole('button', { name: '发送消息 ↑' }).click()
    ])
    assert.equal(submittedResponse.status(), 202)
    const submitted = (await submittedResponse.json()).data
    assert(terminal.url().includes(`/runs/${submitted.id}/events?`))
    phase('browser_sse_headers', { case: fixture.id })
    await page.waitForFunction(count => document.querySelectorAll('.assistant-message-assistant').length === count,
      cases.indexOf(fixture) + 1, { timeout: 15000 })
    await page.getByRole('button', { name: '停止运行', exact: true }).waitFor({ state: 'hidden' })
    await page.waitForFunction(() => document.querySelectorAll('.assistant-cursor, .assistant-runtime-status').length === 0,
      undefined, { timeout: 15000 })
    await page.waitForFunction(() => !document.body.innerText.includes('正在生成回答')
      && !document.body.innerText.includes('正在接收已完成的回复'), undefined, { timeout: 15000 })
    const authoritative = await api(`/assistant/runs/${submitted.id}`, { token })
    assert.equal(authoritative.status, 'succeeded')
    const persisted = await api(`/assistant/conversations/${submitted.conversation_id}/messages?page_size=100`, { token })
    const reply = persisted.list.find(message => message.run_id === submitted.id && message.role === 'assistant')
    assert(reply && !reply.redacted)
    const rendered = page.locator('.assistant-message-assistant .assistant-message-text').nth(cases.indexOf(fixture))
    await page.waitForFunction(({ index, content }) => document.querySelectorAll('.assistant-message-assistant .assistant-message-text')[index]?.textContent === content,
      { index: cases.indexOf(fixture), content: reply.content }, { timeout: 15000 })
    assert.equal(await rendered.textContent(), reply.content)
    phase('browser_reply_rendered', { case: fixture.id })
  }
  phase('browser_history_reload')
  await page.reload()
  await page.waitForSelector('.assistant-message-assistant')
  assert.equal(await page.locator('.assistant-message-assistant').count(), 2)
  assert((await page.locator('.assistant-message-assistant').first().innerText()).includes(manifest.course_a))
  await page.screenshot({ path: path.join(folder, 'browser-desktop.png'), fullPage: true, timeout: 10000 })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(folder, 'browser-mobile.png'), fullPage: true, timeout: 10000 })
  assert.deepEqual(errors, [])
  const report = { boundary: 'Actual Nginx/API/durable-worker/MCP/MySQL/Redis/FAISS; deterministic model+embedding, no cloud-quality claim',
    cases: results, checks: ['12 fixture runs', 'idempotent submission', 'read-only SSE reconnect with unchanged charges',
      '24 persisted messages', 'budget sum and released reservations', 'cross-user 404', 'real login + two-round browser + reload', '390px render'],
    passed: true }
  await fs.writeFile(path.join(folder, 'results.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify({ passed: true, fixtureRuns: results.length, browserRounds: 2, output: folder }))
} catch (error) {
  await page.screenshot({ path: path.join(folder, 'browser-failure.png'), fullPage: true, timeout: 10000 }).catch(() => {})
  await fs.writeFile(path.join(folder, 'browser-failure.json'), JSON.stringify({
    error: error.message, url: page.url(), responses, errors, body: await page.locator('body').innerText().catch(() => '')
  }, null, 2))
  throw error
} finally {
  await browser.close()
}
