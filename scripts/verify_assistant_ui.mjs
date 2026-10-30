/** Synthetic-only browser acceptance. No campus config, database or model access.
 * node scripts/verify_assistant_ui.mjs --dist <production dist> --output <temporary directory>
 *   [--playwright <installed module path>] [--browser <installed executable>] [--port 5184]
 *   [--only <comma-separated case names>]
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'
import { createRequire } from 'node:module'

const options = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, values) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), values[index + 1]])
  return pairs
}, []))
assert(options.dist && options.output, '--dist and --output are required; never point at production services')
const dist = path.resolve(options.dist)
const output = path.resolve(options.output)
await fs.access(path.join(dist, 'index.html'))
await fs.mkdir(output, { recursive: true })
// Keep browser profiles, downloads and temporary files with the test artifacts.
process.env.TEMP = output
process.env.TMP = output
process.env.TMPDIR = output
const require = createRequire(import.meta.url)
const { chromium } = require(options.playwright || 'playwright')
const port = Number(options.port || 5184)
assert(Number.isInteger(port) && port > 1024 && port < 65536)
const origin = `http://127.0.0.1:${port}`
const now = '2026-10-30T00:00:00Z'
const first = '11111111-1111-4111-8111-111111111111'
const second = '22222222-2222-4222-8222-222222222222'
const unsafeText = '<script>window.assistantUnsafe=true</script><img src=x onerror="window.assistantUnsafe=true">'
const answer = `合成回复第一段。${'校园助手流式界面验收。'.repeat(9)}${unsafeText} 合成回复结束。`
const worlds = new Map()
const unexpected = []
const timers = new Set()
const sockets = new Set()
const report = []
let browser

function later(action, delay) {
  const timer = setTimeout(() => { timers.delete(timer); action() }, delay)
  timers.add(timer)
  return timer
}
function conversation(id, title) {
  return { id, title, state: 'active', active_run_id: null, created_at: now, updated_at: now,
    expires_at: '2099-01-01T00:00:00Z' }
}
function message(id, role, content, runId = null) {
  return { id, sequence: id, run_id: runId, role, content, citations: [], redacted: false, created_at: now }
}
function world(name) {
  if (worlds.has(name)) return worlds.get(name)
  const many = name === 'history' || name === 'scroll' || name === 'http-history-deleted'
  const history = many ? Array.from({ length: 104 }, (_, index) => message(index + 1,
    index % 2 ? 'assistant' : 'user', `历史第${index + 1}条。${'旧消息内容。'.repeat(10)}`)) : [
    message(1, 'user', '合成历史问题'), message(2, 'assistant', '合成历史回答')]
  if (name === 'unsafe-history') history[1] = { ...history[1], content: unsafeText,
    citations: [{ source_id: 'S1', kind: 'notice', item_id: 1, title: '恶意来源', url: 'javascript:alert(1)' }] }
  if (['expired', 'not-found', 'http-expired', 'http-management-expired', 'http-cancel-deleted'].includes(name)) history[1].citations = [
    { source_id: 'S1', kind: 'notice', item_id: 1, title: '合成旧通知', url: '/app/notices/1' }]
  const value = { name, conversations: [conversation(first, '合成会话甲'), conversation(second, '合成会话乙')],
    messages: new Map([[first, history], [second, [message(1, 'user', '会话乙问题'), message(2, 'assistant', '会话乙历史回答')]]]),
    runs: new Map(), posts: [], subscriptions: [], cancellations: 0, closed: 0, staleHistoryDelivered: false }
  worlds.set(name, value)
  return value
}
function envelope(response, data, status = 200) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
  response.end(JSON.stringify({ code: status < 400 ? 200 : status, message: '合成界面验收', data }))
}
function pageList(list, url) {
  const page = Number(url.searchParams.get('page') || 1)
  const pageSize = Number(url.searchParams.get('page_size') || 20)
  return { list: list.slice((page - 1) * pageSize, page * pageSize), total: list.length, page, page_size: pageSize }
}
async function body(request) {
  let result = ''
  for await (const block of request) { result += block; assert(result.length < 20000) }
  return result ? JSON.parse(result) : {}
}
function createRun(value, conversationId, data) {
  const previous = [...value.runs.values()].find(run => run.conversation_id === conversationId && run.key === data.request_key)
  if (previous) return previous
  const id = `33333333-3333-4333-8333-${String(value.runs.size + 1).padStart(12, '0')}`
  const run = { id, conversation_id: conversationId, status: 'queued', reason: null,
    cancel_requested: false, model_calls: 0, tool_calls: 0, cost_limit: '0.10', reserved: '0.10', spent: '0',
    budget_day: '2026-10-30', created_at: now, started_at: null, finished_at: null,
    deadline_at: '2099-01-01T00:00:00Z', key: data.request_key, attempts: 0 }
  value.runs.set(id, run)
  value.conversations.find(item => item.id === conversationId).active_run_id = id
  const list = value.messages.get(conversationId)
  list.push(message(list.length + 1, 'user', data.content, id))
  return run
}
function publicRun(run) {
  const { key, attempts, reply, ...result } = run
  return result
}
function complete(value, run) {
  if (run.status !== 'succeeded') {
    run.status = 'succeeded'; run.model_calls = 1; run.spent = '0.001'; run.reserved = '0'
    run.finished_at = now
    const list = value.messages.get(run.conversation_id)
    run.reply = { ...message(list.length + 1, 'assistant', answer, run.id),
      citations: [{ source_id: 'S1', kind: 'notice', item_id: 1, title: '合成通知', url: '/app/notices/1' }] }
    list.push(run.reply)
    value.conversations.find(item => item.id === run.conversation_id).active_run_id = null
  }
}
function subscribe(value, run, response, url) {
  run.attempts += 1
  const attempt = run.attempts
  const after = Number(url.searchParams.get('after') || 0)
  value.subscriptions.push({ id: run.id, after })
  if (value.name === 'not-found') return envelope(response, null, 404)
  response.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-store, no-transform', 'X-Accel-Buffering': 'no' })
  response.flushHeaders()
  const frame = (kind, data, sequence) => {
    if (response.destroyed || response.writableEnded) return
    response.write(`${sequence ? `id: ${sequence}\n` : ''}event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`)
  }
  const done = () => { frame('done', { run: publicRun(run), message: run.reply || null }); response.end() }
  response.once('close', () => { value.closed += 1 })
  if (run.status !== 'succeeded') run.status = 'running'
  run.started_at = now; run.model_calls = 1
  frame('status', { run: publicRun(run) })
  if (value.name === 'expired') {
    later(() => frame('delta', { run_id: run.id, sequence: 1, text: '已到达但尚未完成的回复' }, 1), 100)
    later(() => { frame('error', { reason: 'expired' }); response.end() }, 700)
    return
  }
  if (value.name === 'cancel' || value.name === 'logout' || value.name === 'session-expired' || value.name === 'http-cancel-deleted'
      || (value.name === 'cancel-success' && attempt === 1)) {
    const check = () => {
      if (response.destroyed) return
      if (run.status === 'cancelled') return done()
      if (value.name === 'session-expired') {
        frame('error', { reason: 'unauthenticated' }); response.end(); return
      }
      frame('status', { run: publicRun(run) }); later(check, 100)
    }
    later(check, 250)
    return
  }
  const chunks = Array.from(answer).reduce((parts, character, index) => {
    const part = Math.floor(index / 64); parts[part] = (parts[part] || '') + character; return parts
  }, [])
  const firstDelay = value.name === 'switch' ? 1300 : 150
  later(() => complete(value, run), firstDelay - 10)
  for (let index = 0; index < chunks.length; ++index) {
    later(() => {
      if (index + 1 > after) frame('delta', { run_id: run.id, sequence: index + 1, text: chunks[index] }, index + 1)
      if (value.name === 'reconnect' && attempt === 1 && index === 0) response.destroy()
    }, firstDelay + index * 330)
  }
  later(done, firstDelay + chunks.length * 330 + 100)
}

const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2' }
const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, origin)
    if (!url.pathname.startsWith('/api/')) {
      let file = path.resolve(dist, '.' + decodeURIComponent(url.pathname))
      if (file !== dist && !file.startsWith(dist + path.sep)) { response.writeHead(404); response.end(); return }
      try { if (!(await fs.stat(file)).isFile()) file = path.join(dist, 'index.html') }
      catch { file = path.join(dist, 'index.html') }
      response.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' })
      response.end(await fs.readFile(file)); return
    }
    assert(!url.search.includes('token') && !url.search.includes('Bearer'), 'Credential must not enter URL')
    const token = String(request.headers.authorization || '')
    if (!token.startsWith('Bearer synthetic-')) return envelope(response, null, 401)
    const value = world(token.slice('Bearer synthetic-'.length))
    const method = request.method
    const pathname = url.pathname
    if (pathname === '/api/user/me') return envelope(response, { id: 1, username: 'synthetic', name: '合成学生',
      role: 'student', email: null, phone: null, avatar: null, status: 1 })
    if (pathname === '/api/auth/logout') return envelope(response, null)
    if (pathname === '/api/assistant/budget') return envelope(response, { day: '2026-10-30', currency: 'CNY',
      user: { cap: '1', spent: '0.001', reserved: '0', available: '0.999', estimated: true },
      policy: { enabled: value.name !== 'disabled', allow_campus_data: value.name !== 'disabled',
        run_cost_limit: '0.1', alert_ratio: '0.8', retention_days: 7 } })
    if (pathname === '/api/assistant/conversations') {
      if (method === 'POST') {
        const item = conversation('44444444-4444-4444-8444-444444444444', '新会话')
        value.conversations.unshift(item); value.messages.set(item.id, []); return envelope(response, item, 201)
      }
      return envelope(response, pageList(value.conversations, url))
    }
    const selected = pathname.match(/^\/api\/assistant\/conversations\/([^/]+)(?:\/(messages|runs))?$/)
    if (selected) {
      const item = value.conversations.find(item => item.id === selected[1])
      if (!item) return envelope(response, null, 404)
      if (selected[2] === 'messages') {
        if (value.name === 'http-history-deleted' && url.searchParams.get('page') === '2') return envelope(response, null, 404)
        const snapshot = pageList(value.messages.get(item.id), url)
        if (value.name === 'delayed-history' && value.posts.length && !value.staleHistoryDelivered) {
          value.staleHistoryDelivered = true
          const stale = structuredClone(snapshot)
          later(() => { if (!response.destroyed) envelope(response, stale) }, 2400)
          return
        }
        return envelope(response, snapshot)
      }
      if (selected[2] === 'runs' && method === 'POST') {
        const data = await body(request)
        assert.deepEqual(Object.keys(data).sort(), ['content', 'request_key'])
        value.posts.push({ ...data, conversationId: item.id })
        if (value.name === 'http-expired') return envelope(response, null, 410)
        const run = createRun(value, item.id, data)
        if (value.name === 'timeout' && value.posts.length === 1) {
          later(() => { if (!response.destroyed) envelope(response, publicRun(run), 202) }, 14000)
          return
        }
        return envelope(response, publicRun(run), 202)
      }
      if (method === 'PATCH' && value.name === 'http-management-expired') return envelope(response, null, 410)
      if (method === 'PATCH') Object.assign(item, await body(request))
      if (method === 'DELETE') value.conversations = value.conversations.filter(other => other.id !== item.id)
      return envelope(response, item)
    }
    const runMatch = pathname.match(/^\/api\/assistant\/runs\/([^/]+)(?:\/(events|cancel))?$/)
    if (runMatch) {
      const run = value.runs.get(runMatch[1])
      if (!run) return envelope(response, null, 404)
      if (runMatch[2] === 'events') return subscribe(value, run, response, url)
      if (runMatch[2] === 'cancel') {
        value.cancellations += 1
        if (value.name === 'http-cancel-deleted') return envelope(response, null, 404)
        if (value.name === 'cancel-success') complete(value, run)
        else {
          run.status = 'cancelled'; run.reason = 'cancelled'; run.reserved = '0'
          run.cancel_requested = true; run.finished_at = now
        }
        value.conversations.find(item => item.id === run.conversation_id).active_run_id = null
      }
      return envelope(response, publicRun(run))
    }
    unexpected.push(`${method} ${pathname}`)
    envelope(response, null, 404)
  } catch { unexpected.push('synthetic fixture handler failure'); response.writeHead(500); response.end('synthetic fixture failure') }
})
server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)) })

async function fixture(name, test, viewport = { width: 1440, height: 1000 }) {
  if (options.only && !options.only.split(',').includes(name)) return
  const context = await browser.newContext({ viewport, timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce' })
  const errors = []
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await context.route('**/*', route => {
    const value = new URL(route.request().url())
    if (value.origin === origin || value.protocol === 'blob:' || value.protocol === 'data:') return route.continue()
    unexpected.push(`external ${value.origin}`); return route.abort()
  })
  await page.addInitScript(token => localStorage.setItem('campus_token', token), `synthetic-${name}`)
  try {
    await page.goto(`${origin}/app/assistant`)
    await page.getByRole('heading', { name: '校园助手', exact: true }).waitFor()
    await page.getByText(name === 'unsafe-history' ? unsafeText : ['history', 'scroll', 'http-history-deleted'].includes(name)
      ? '历史第104条。' + '旧消息内容。'.repeat(10) : '合成历史回答', { exact: true }).waitFor()
    await test(page, world(name))
    assert.deepEqual(errors, [], 'Unexpected browser exception')
    report.push({ name, status: 'passed' })
    console.log(`PASS ${name}`)
  } catch (error) {
    report.push({ name, status: 'failed' })
    await page.screenshot({ path: path.join(output, `assistant-${name}-failure.png`), fullPage: true }).catch(() => {})
    await fs.writeFile(path.join(output, 'assistant-ui-report.json'), JSON.stringify({ synthetic_only: true, cases: report }, null, 2))
    throw error
  } finally { await context.close() }
}
async function send(page, value = '新的合成问题') {
  await page.getByRole('textbox', { name: '发送消息', exact: true }).fill(value)
  await page.getByRole('button', { name: '发送消息 ↑', exact: true }).click()
}
const bodyText = page => page.locator('.assistant-message-text')
async function finished(page, count = 1) {
  await page.waitForFunction(({ text, count }) => Array.from(document.querySelectorAll('.assistant-message-text'))
    .filter(element => element.textContent.trim() === text).length >= count, { text: answer, count }, { timeout: 18000 })
}

try {
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve) })
  browser = await chromium.launch({ headless: true, ...(options.browser ? { executablePath: options.browser } : {}),
    downloadsPath: path.join(output, 'downloads') })
  await fixture('stream', async (page, value) => {
    await send(page)
    await page.getByText('正在接收已完成的回复', { exact: true }).waitFor()
    const partial = await bodyText(page).last().innerText()
    assert(partial.length > 0 && !partial.includes('合成回复结束。'), 'Must render before final segment')
    await finished(page)
    assert.equal(value.posts.length, 1)
    assert.equal(await page.evaluate(() => window.assistantUnsafe), undefined)
    assert.equal(await page.locator('.assistant-message-text script, .assistant-message-text img').count(), 0)
    assert.equal(await page.getByRole('link', { name: /合成通知/ }).getAttribute('href'), '/app/notices/1')
    await send(page, '第二轮合成追问')
    await finished(page, 2)
    assert.equal(value.posts.length, 2)
    assert.equal(value.posts[0].conversationId, value.posts[1].conversationId)
    assert.notEqual(value.posts[0].request_key, value.posts[1].request_key)
    await page.screenshot({ path: path.join(output, 'assistant-desktop.png'), fullPage: true })
  })
  await fixture('history', async (page, value) => {
    assert.equal(await bodyText(page).filter({ hasText: '历史第1条。' }).count(), 0)
    await page.getByRole('button', { name: '加载更早消息', exact: true }).click()
    await page.getByText('历史第54条。' + '旧消息内容。'.repeat(10), { exact: true }).waitFor()
    assert.equal(value.posts.length, 0)
  })
  await fixture('reconnect', async (page, value) => {
    await send(page)
    await finished(page)
    assert(value.subscriptions.length >= 2, 'Interrupted read must reconnect')
    assert.equal(value.posts.length, 1, 'Reconnect must never re-admit model work')
    assert.equal(await bodyText(page).filter({ hasText: answer }).count(), 1)
  })
  await fixture('timeout', async (page, value) => {
    await send(page)
    await page.getByRole('button', { name: '确认原提交结果', exact: true }).waitFor({ timeout: 16000 })
    assert.equal(value.posts.length, 1)
    await page.getByRole('button', { name: '确认原提交结果', exact: true }).click()
    await finished(page)
    assert.equal(value.posts.length, 2)
    assert.equal(value.runs.size, 1, 'Ambiguous POST must retain the original idempotency key')
    assert.equal(value.posts[0].request_key, value.posts[1].request_key)
  })
  await fixture('cancel', async (page, value) => {
    await send(page)
    await page.getByRole('button', { name: '停止运行', exact: true }).click()
    await page.getByText('运行已取消。', { exact: true }).waitFor()
    assert.equal(value.cancellations, 1)
    assert.equal(value.posts.length, 1)
    assert.equal(await bodyText(page).filter({ hasText: '合成回复结束。' }).count(), 0)
  })
  await fixture('cancel-success', async (page, value) => {
    await send(page)
    await page.getByRole('button', { name: '停止运行', exact: true }).click()
    await finished(page)
    assert.equal(value.cancellations, 1)
    assert.equal(value.posts.length, 1, 'Successful cancellation race must only resubscribe to the original run')
    assert(value.subscriptions.length >= 2)
    assert.equal(await bodyText(page).filter({ hasText: answer }).count(), 1)
  })
  for (const name of ['http-expired', 'http-history-deleted', 'http-management-expired', 'http-cancel-deleted']) {
    await fixture(name, async (page, value) => {
      if (name === 'http-history-deleted') await page.getByRole('button', { name: '加载更早消息', exact: true }).click()
      else if (name === 'http-management-expired') await page.getByRole('button', { name: '归档', exact: true }).click()
      else {
        await send(page)
        if (name === 'http-cancel-deleted') await page.getByRole('button', { name: '停止运行', exact: true }).click()
      }
      await page.getByText('合成界面验收', { exact: true }).waitFor()
      const visible = await page.getByRole('log', { name: '对话消息' }).innerText()
      assert(!/合成历史|历史第\d+条|新的合成问题/.test(visible), 'HTTP 404/410 must immediately remove unavailable conversation bodies')
      assert.equal(await page.getByRole('link', { name: /合成旧通知/ }).count(), 0)
      assert(await page.getByRole('textbox', { name: '发送消息', exact: true }).isDisabled())
      assert.equal(await page.getByRole('button', { name: '重新连接原运行', exact: true }).count(), 0)
      assert(value.posts.length <= 1, 'HTTP failures must not replay model work')
    })
  }
  await fixture('delayed-history', async (page, value) => {
    await send(page)
    await finished(page)
    // The post-admission HTTP snapshot intentionally contains only the user
    // message and returns after the authoritative SSE done reply.
    await page.waitForTimeout(2700)
    assert(value.staleHistoryDelivered)
    assert.equal(await bodyText(page).filter({ hasText: answer }).count(), 1)
    assert.equal(value.posts.length, 1)
  })
  await fixture('expired', async (page, value) => {
    await page.getByRole('link', { name: /合成旧通知/ }).waitFor()
    await send(page)
    await page.getByText('正在接收已完成的回复', { exact: true }).waitFor()
    await page.getByText('回复已过期，请重新创建会话。', { exact: true }).waitFor()
    await page.waitForTimeout(2200)
    assert.equal(value.subscriptions.length, 1)
    assert.equal(value.posts.length, 1)
    assert.equal(await page.getByRole('link', { name: /合成旧通知/ }).count(), 0)
    assert(!await page.getByRole('log', { name: '对话消息' }).innerText().then(text => /合成历史|已到达但尚未完成/.test(text)))
    assert(await page.getByRole('textbox', { name: '发送消息', exact: true }).isDisabled())
    assert.equal(await page.getByRole('button', { name: '重新连接原运行', exact: true }).count(), 0)
    assert.equal(await page.getByRole('button', { name: '停止运行', exact: true }).count(), 0)
  })
  await fixture('not-found', async (page, value) => {
    await send(page)
    await page.getByText('运行不存在或已删除。', { exact: true }).waitFor()
    await page.waitForTimeout(2200)
    assert.equal(value.subscriptions.length, 1)
    assert.equal(value.posts.length, 1)
    assert.equal(await bodyText(page).count(), 0)
    assert(await page.getByRole('textbox', { name: '发送消息', exact: true }).isDisabled())
    assert.equal(await page.getByRole('button', { name: '重新连接原运行', exact: true }).count(), 0)
  })
  await fixture('switch', async (page, value) => {
    await send(page)
    await page.getByRole('button', { name: /合成会话乙/ }).click()
    await page.getByText('会话乙历史回答', { exact: true }).waitFor()
    await page.waitForTimeout(2600)
    assert.equal(await bodyText(page).filter({ hasText: '合成回复' }).count(), 0)
    assert(value.closed >= 1, 'Switch must close the old subscription')
    assert.equal(value.posts.length, 1)
  })
  await fixture('logout', async (page, value) => {
    await send(page)
    await page.getByRole('button', { name: '退出', exact: true }).click()
    await page.waitForURL(`${origin}/login`)
    assert.equal(await page.evaluate(() => localStorage.getItem('campus_token')), null)
    assert.equal(await page.locator('.assistant-message-text').count(), 0)
    assert(value.closed >= 1)
  })
  await fixture('session-expired', async (page) => {
    await send(page)
    await page.waitForFunction(() => localStorage.getItem('campus_token') === null)
    assert.equal(await bodyText(page).count(), 0)
  })
  await fixture('scroll', async (page) => {
    await send(page)
    const scroll = page.locator('.assistant-message-scroll')
    await scroll.evaluate(element => { element.scrollTop = 0; element.dispatchEvent(new Event('scroll')) })
    await finished(page)
    assert(await scroll.evaluate(element => element.scrollTop < element.scrollHeight - element.clientHeight - 90))
    await page.getByRole('button', { name: '回到最新消息 ↓', exact: true }).click()
    await page.waitForFunction(() => { const element = document.querySelector('.assistant-message-scroll');
      return element.scrollHeight - element.scrollTop - element.clientHeight < 90 })
  })
  await fixture('unsafe-history', async (page) => {
    assert.equal(await page.evaluate(() => window.assistantUnsafe), undefined)
    assert.equal(await page.locator('a[href^="javascript:"]').count(), 0)
    assert.equal(await page.locator('.assistant-message-text script, .assistant-message-text img').count(), 0)
  })
  await fixture('disabled', async (page, value) => {
    assert(await page.getByRole('textbox', { name: '发送消息', exact: true }).isDisabled())
    assert(await page.getByRole('button', { name: '发送消息 ↑', exact: true }).isDisabled())
    await page.getByText('助手尚未启用：当前可以管理历史会话，暂不能发送问题。校园数据外发保持关闭。', { exact: true }).waitFor()
    assert.equal(value.posts.length, 0)
  })
  await fixture('mobile', async (page) => {
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
    await page.getByRole('textbox', { name: '发送消息', exact: true }).scrollIntoViewIfNeeded()
    await send(page)
    await finished(page)
    await page.screenshot({ path: path.join(output, 'assistant-mobile.png'), fullPage: true })
  }, { width: 390, height: 844 })
  assert.deepEqual(unexpected, [], 'All API/network access must remain in the synthetic fixture')
  await fs.writeFile(path.join(output, 'assistant-ui-report.json'), JSON.stringify({ synthetic_only: true, cases: report }, null, 2))
  console.log(`PASS ${report.length} synthetic UI cases; no campus configuration, database or cloud access.`)
} finally {
  await browser?.close()
  for (const timer of timers) clearTimeout(timer)
  for (const socket of sockets) socket.destroy()
  await new Promise(resolve => server.close(resolve))
}
