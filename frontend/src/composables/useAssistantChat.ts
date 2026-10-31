import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, errorMessage } from '../utils/campus-request'
import { token } from '../utils/campus-auth'
import { readToken } from '../utils/session-storage'
import { assistantBudgetApi, cancelRunApi, conversationApi, conversationsApi, createConversationApi,
  createRunApi, deleteConversationApi, getRunApi, messagesApi, subscribeRun, updateConversationApi } from '../api/assistant'
import { assistantAlertsApi, acknowledgeAlertApi } from '../api/assistant'
import type { AssistantAlert, AssistantBudget, AssistantMessage, AssistantRun, Conversation } from '../api/assistant'

export const terminalRun = (run: AssistantRun | null) => !run || ['succeeded', 'failed', 'cancelled', 'expired'].includes(run.status)
export function runReason(reason: string | null): string {
  const reasons: Record<string, string> = { budget_exceeded: '预算不足，本次运行已停止。', cancelled: '运行已取消。',
    worker_stopped: '运行因服务停止而结束，可重新输入问题。', interrupted: '运行已中断，未自动重放付费请求。',
    queue_expired: '排队已超时，请稍后重新提交。', timeout: '运行等待超时，已保守结算可能发生的费用。',
    unauthenticated: '登录已失效，未保存新的回答。', forbidden: '当前身份无权继续运行。',
    usage_unknown: '上游用量无法确认，已保守记账并停止后续调用。', pricing_missing: '计价尚未配置，请联系管理员。',
    configuration_missing: '模型尚未配置，请联系管理员。', rate_limited: '服务繁忙，本次运行已结束。',
    context_limit: '当前上下文超过容量，请新建会话继续。', context_expired: '会话正文已到期，请新建会话。',
    model_limit: '已达到本次模型调用上限。', tool_limit: '已达到本次工具调用上限。' }
  return reasons[reason ?? ''] ?? '运行暂未完成，请检查状态后再决定是否重新提交。'
}

export function useAssistantChat() {
  const conversations = ref<Conversation[]>([])
  const conversationTotal = ref(0)
  const selected = ref<Conversation | null>(null)
  const budget = ref<AssistantBudget | null>(null)
  const alerts = ref<AssistantAlert[]>([])
  const alertTotal = ref(0)
  const alertsLoading = ref(false)
  const alertsError = ref('')
  const alertPending = ref<number | null>(null)
  let alertPage = 1
  let alertGeneration = 0
  const acknowledged = new Set<number>()
  const messages = ref<AssistantMessage[]>([])
  const activeRun = ref<AssistantRun | null>(null)
  const input = ref('')
  const partial = ref('')
  const loading = ref(false)
  const loadingMessages = ref(false)
  const loadingOlder = ref(false)
  const submitting = ref(false)
  const changing = ref(false)
  const cancelling = ref(false)
  const error = ref('')
  const sendError = ref('')
  const streamError = ref('')
  const budgetError = ref('')
  const connection = ref<'idle' | 'connecting' | 'waiting' | 'receiving' | 'reconnecting' | 'interrupted'>('idle')
  const pending = ref<{ conversationId: string; content: string; key: string } | null>(null)
  const olderPage = ref(0)
  let listPage = 1
  let alive = true
  let selection = 0
  let reconnect = 0
  let currentController = new AbortController()
  let streamController: AbortController | null = null
  const lifetime = new AbortController()
  const sessionToken = token.value

  const running = computed(() => !terminalRun(activeRun.value))
  const ready = computed(() => Boolean(budget.value?.policy.enabled && budget.value.policy.allow_campus_data))
  const canSend = computed(() => ready.value && selected.value?.state === 'active' && !running.value
    && !submitting.value && !loadingMessages.value && !changing.value && !pending.value
    && !['connecting', 'waiting', 'receiving', 'reconnecting'].includes(connection.value) && Boolean(input.value.trim()))
  const canLoadOlder = computed(() => olderPage.value > 0)
  const statusText = computed(() => {
    if (connection.value === 'receiving') return '正在接收已完成的回复'
    if (connection.value === 'connecting') return '正在连接运行'
    if (connection.value === 'reconnecting') return '连接中断，正在重新订阅原运行'
    if (connection.value === 'interrupted') return '连接中断，运行仍可能继续'
    if (activeRun.value?.cancel_requested && running.value) return '正在停止，请等待服务端确认'
    if (activeRun.value?.status === 'queued') return '任务排队中'
    if (activeRun.value?.status === 'running') return '正在生成回答'
    return ''
  })
  const sameSession = () => alive && token.value === sessionToken && readToken() === sessionToken && Boolean(sessionToken)
  const current = (sequence: number) => sameSession() && selection === sequence

  function stopSubscription() { ++reconnect; streamController?.abort(); streamController = null; connection.value = 'idle'; partial.value = '' }
  function resetSelection() {
    ++selection
    stopSubscription()
    currentController.abort()
    currentController = new AbortController()
    selected.value = null; messages.value = []; activeRun.value = null; pending.value = null; input.value = ''
    sendError.value = streamError.value = ''; olderPage.value = 0
    loadingMessages.value = loadingOlder.value = submitting.value = cancelling.value = changing.value = false
    return selection
  }
  function updateListed(value: Conversation) {
    const index = conversations.value.findIndex(item => item.id === value.id)
    if (index >= 0) conversations.value[index] = value
    else conversations.value.unshift(value)
  }
  function invalidateConversation(cause: unknown, sequence: number) {
    if (!current(sequence) || !(cause instanceof ApiError) || ![404, 410].includes(cause.status)) return false
    const conversation = selected.value
    const redacted = cause.status === 410
      ? messages.value.map(message => ({ ...message, content: null, citations: [], redacted: true })) : []
    // Both HTTP and SSE can discover deletion or expiry. Invalidate pending
    // reads before clearing bodies so a late snapshot cannot restore them.
    resetSelection()
    messages.value = redacted
    if (conversation) {
      selected.value = { ...conversation, state: cause.status === 410 ? 'expired' : 'deleted',
        title: cause.status === 410 ? '已过期会话' : conversation.title, active_run_id: null }
      updateListed(selected.value)
    }
    error.value = errorMessage(cause)
    return true
  }
  async function refreshAlerts(more = false) {
    if (more && alertsLoading.value) return
    const generation = ++alertGeneration
    const page = more ? alertPage + 1 : 1
    alertsLoading.value = true
    try {
      const data = await assistantAlertsApi(page, lifetime.signal)
      if (!sameSession() || generation !== alertGeneration) return
      const rows = data.list.map(item => ({ ...item, acknowledged: item.acknowledged || acknowledged.has(item.id) }))
      alerts.value = more ? [...new Map([...alerts.value, ...rows].map(item => [item.id, item])).values()] : rows
      alertPage = page; alertTotal.value = data.total; alertsError.value = ''
    } catch (cause) { if (sameSession() && generation === alertGeneration) alertsError.value = errorMessage(cause) }
    finally { if (sameSession() && generation === alertGeneration) alertsLoading.value = false }
  }
  async function acknowledgeAlert(id: number) {
    if (alertPending.value !== null || !sameSession()) return
    alertPending.value = id
    try {
      await acknowledgeAlertApi(id, lifetime.signal)
      if (!sameSession()) return
      acknowledged.add(id)
      alerts.value = alerts.value.map(item => item.id === id ? { ...item, acknowledged: true } : item)
      alertsError.value = ''
    } catch (cause) { if (sameSession()) alertsError.value = errorMessage(cause) }
    finally { if (sameSession()) alertPending.value = null }
  }
  async function refreshBudget() {
    void refreshAlerts()
    try {
      const data = await assistantBudgetApi(lifetime.signal)
      if (sameSession() && !lifetime.signal.aborted) { budget.value = data; budgetError.value = '' }
    } catch (cause) { if (sameSession() && !lifetime.signal.aborted) budgetError.value = errorMessage(cause) }
  }
  async function loadLatest(sequence: number, id: string) {
    const signal = currentController.signal
    let data = await messagesApi(id, 1, signal)
    const last = Math.max(1, Math.ceil(data.total / 50))
    if (last > 1) data = await messagesApi(id, last, signal)
    if (!current(sequence)) return
    // A completed SSE event may arrive while this HTTP snapshot is in flight.
    // Preserve its newer committed message instead of hiding it with old data.
    const newest = Math.max(0, ...data.list.map(item => item.sequence))
    const arrived = messages.value.filter(item => item.sequence > newest && item.run_id === activeRun.value?.id)
    messages.value = [...data.list, ...arrived]
    olderPage.value = last - 1
  }
  async function loadOlder() {
    if (!selected.value || !canLoadOlder.value || loadingOlder.value) return
    const sequence = selection
    loadingOlder.value = true
    try {
      const data = await messagesApi(selected.value.id, olderPage.value, currentController.signal)
      if (!current(sequence)) return
      const seen = new Set(messages.value.map(item => item.id))
      messages.value = [...data.list.filter(item => !seen.has(item.id)), ...messages.value]
      --olderPage.value
    } catch (cause) { if (!invalidateConversation(cause, sequence) && current(sequence)) error.value = errorMessage(cause) }
    finally { if (current(sequence)) loadingOlder.value = false }
  }

  async function connectRun(run: AssistantRun, sequence = selection) {
    ++reconnect
    const subscription = reconnect
    streamController?.abort()
    const controller = new AbortController()
    streamController = controller
    streamError.value = ''; partial.value = ''; connection.value = 'connecting'
    const valid = () => current(sequence) && subscription === reconnect && !controller.signal.aborted
    for (let attempt = 0; attempt < 3 && valid(); ++attempt) {
      let last = 0
      partial.value = ''
      try {
        await subscribeRun(run.id, event => {
          if (!valid()) return
          if (event.type === 'delta') {
            if (event.sequence <= last) return
            if (event.sequence !== last + 1 || partial.value.length + event.text.length > 32000) {
              throw new ApiError('回复分段不连续，请重新连接。', 502)
            }
            last = event.sequence; partial.value += event.text; connection.value = 'receiving'
          } else {
            if (event.run.conversation_id !== selected.value?.id) throw new ApiError('会话状态不匹配。', 502)
            activeRun.value = event.run
            if (event.type === 'status') {
              if (!partial.value) connection.value = 'waiting'
            } else {
              if (event.message) {
                messages.value = [...messages.value.filter(item => item.id !== event.message?.id), event.message]
                  .sort((first, second) => first.sequence - second.sequence)
              }
              partial.value = ''; connection.value = 'idle'
              if (selected.value) { selected.value.active_run_id = null; updateListed(selected.value) }
              void refreshBudget()
            }
          }
        }, controller.signal)
        return
      } catch (cause) {
        if (!valid()) return
        if (cause instanceof ApiError && cause.status === 401) { partial.value = ''; return }
        if (invalidateConversation(cause, sequence)) return
        // Only reconnect the read subscription. No POST/model request is retried.
        if (attempt < 2 && (!(cause instanceof ApiError) || [0, 502, 503].includes(cause.status))) {
          partial.value = ''; connection.value = 'reconnecting'
          await new Promise(resolve => window.setTimeout(resolve, (attempt + 1) * 1000))
          continue
        }
        partial.value = ''; connection.value = 'interrupted'; streamError.value = errorMessage(cause)
        return
      }
    }
  }

  async function selectConversation(id: string) {
    const sequence = resetSelection()
    loadingMessages.value = true; error.value = ''
    try {
      const conversation = await conversationApi(id, currentController.signal)
      if (!current(sequence)) return
      selected.value = conversation; updateListed(conversation)
      await loadLatest(sequence, id)
      if (!current(sequence)) return
      if (conversation.active_run_id) {
        const run = await getRunApi(conversation.active_run_id, currentController.signal)
        if (!current(sequence)) return
        activeRun.value = run
        if (!terminalRun(run)) void connectRun(run, sequence)
        else await loadLatest(sequence, id)
      }
    } catch (cause) { if (!invalidateConversation(cause, sequence) && current(sequence)) error.value = errorMessage(cause) }
    finally { if (current(sequence)) loadingMessages.value = false }
  }
  async function reload() {
    if (loading.value) return
    loading.value = true; error.value = ''
    const sequence = selection
    try {
      const [data] = await Promise.all([conversationsApi(1, lifetime.signal), refreshBudget()])
      if (!current(sequence)) return
      conversations.value = data.list; conversationTotal.value = data.total; listPage = 1
      if (selected.value) await selectConversation(selected.value.id)
      else if (data.list[0]) await selectConversation(data.list[0].id)
    } catch (cause) { if (current(sequence)) error.value = errorMessage(cause) }
    finally { if (alive) loading.value = false }
  }
  async function loadMoreConversations() {
    if (loading.value || conversations.value.length >= conversationTotal.value) return
    loading.value = true
    try {
      const data = await conversationsApi(listPage + 1, lifetime.signal)
      if (!sameSession() || lifetime.signal.aborted) return
      const seen = new Set(conversations.value.map(item => item.id))
      conversations.value.push(...data.list.filter(item => !seen.has(item.id)))
      conversationTotal.value = data.total; ++listPage
    } catch (cause) { if (alive) error.value = errorMessage(cause) }
    finally { if (alive) loading.value = false }
  }
  async function newConversation() {
    if (changing.value || submitting.value) return
    changing.value = true
    const sequence = selection
    try {
      const value = await createConversationApi(currentController.signal)
      if (!current(sequence)) return
      updateListed(value); ++conversationTotal.value
      await selectConversation(value.id)
    } catch (cause) { if (current(sequence)) error.value = errorMessage(cause) }
    finally { if (current(sequence)) changing.value = false }
  }
  async function changeConversation(remove = false) {
    if (!selected.value || running.value || changing.value || submitting.value || pending.value) return
    const sequence = selection
    const previous = selected.value
    changing.value = true; error.value = ''
    try {
      if (remove) {
        await deleteConversationApi(previous.id, currentController.signal)
        if (!current(sequence)) return
        conversations.value = conversations.value.filter(item => item.id !== previous.id)
        --conversationTotal.value; resetSelection()
      } else {
        const value = await updateConversationApi(previous.id, previous.state === 'archived' ? 'active' : 'archived', currentController.signal)
        if (!current(sequence)) return
        selected.value = value; updateListed(value)
      }
    } catch (cause) { if (!invalidateConversation(cause, sequence) && current(sequence)) error.value = errorMessage(cause) }
    finally { if (current(sequence)) changing.value = false }
  }
  async function submit(recover = false) {
    if (submitting.value || !selected.value || (!recover && !canSend.value)) return
    const sequence = selection
    const id = selected.value.id
    const payload = recover ? pending.value : { conversationId: id, content: input.value.trim(), key: crypto.randomUUID().replace(/-/g, '') }
    if (!payload || payload.conversationId !== id) return
    pending.value = payload; submitting.value = true; sendError.value = ''; streamError.value = ''
    try {
      const run = await createRunApi(id, payload.content, payload.key, currentController.signal)
      if (!current(sequence)) return
      pending.value = null; input.value = ''; activeRun.value = run
      selected.value.active_run_id = terminalRun(run) ? null : run.id; updateListed(selected.value)
      if (!terminalRun(run)) void connectRun(run, sequence)
      await loadLatest(sequence, id)
      void refreshBudget()
    } catch (cause) {
      if (!current(sequence)) return
      if (invalidateConversation(cause, sequence)) return
      // A missing response can follow a committed admission. Keep the original
      // key and offer an explicit idempotent recovery rather than charging twice.
      const ambiguous = !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500
      if (!ambiguous) pending.value = null
      sendError.value = errorMessage(cause)
    } finally { if (current(sequence)) submitting.value = false }
  }
  async function cancel() {
    if (!activeRun.value || !running.value || cancelling.value) return
    const sequence = selection
    cancelling.value = true
    try {
      const run = await cancelRunApi(activeRun.value.id, currentController.signal)
      if (!current(sequence)) return
      activeRun.value = run
      if (run.status === 'succeeded') void connectRun(run, sequence)
      else if (terminalRun(run)) { stopSubscription(); if (selected.value) selected.value.active_run_id = null; void refreshBudget() }
      else if (connection.value === 'interrupted' || connection.value === 'idle') void connectRun(run, sequence)
    } catch (cause) { if (!invalidateConversation(cause, sequence) && current(sequence)) streamError.value = errorMessage(cause) }
    finally { if (current(sequence)) cancelling.value = false }
  }
  function reconnectRun() { if (activeRun.value) void connectRun(activeRun.value) }

  watch(token, () => {
    lifetime.abort(); resetSelection(); conversations.value = []; budget.value = null
    ++alertGeneration; alerts.value = []; alertTotal.value = 0; acknowledged.clear(); alertPending.value = null; alertsError.value = ''; alertsLoading.value = false
    error.value = '登录状态已变化，请重新进入助手页面。'
  })
  onMounted(reload)
  onBeforeUnmount(() => { alive = false; resetSelection(); lifetime.abort() })
  return { conversations, conversationTotal, selected, budget, messages, activeRun, input, partial,
    alerts, alertTotal, alertsLoading, alertsError, alertPending, refreshAlerts, acknowledgeAlert,
    loading, loadingMessages, loadingOlder, submitting, changing, cancelling, error, sendError, streamError,
    budgetError, connection, pending, running, ready, canSend, canLoadOlder, statusText, reload, refreshBudget,
    selectConversation, newConversation, changeConversation, loadOlder, loadMoreConversations, submit, cancel, reconnectRun }
}
