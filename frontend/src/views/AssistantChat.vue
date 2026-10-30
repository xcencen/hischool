<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import AssistantMessages from '../components/assistant/AssistantMessages.vue'
import AssistantComposer from '../components/assistant/AssistantComposer.vue'
import { runReason, useAssistantChat } from '../composables/useAssistantChat'

const chat = useAssistantChat()
const { conversations, conversationTotal, selected, budget, messages, activeRun, input, partial, loading,
  loadingMessages, loadingOlder, submitting, changing, cancelling, error, sendError, streamError, budgetError,
  connection, pending, running, ready, canSend, canLoadOlder, statusText } = chat
const messageList = ref<InstanceType<typeof AssistantMessages> | null>(null)
const receiving = computed(() => ['connecting', 'waiting', 'receiving', 'reconnecting'].includes(connection.value))
const composerHint = computed(() => !selected.value ? '请先新建或选择会话。' : selected.value.state !== 'active'
  ? '会话已归档或到期，请恢复归档或新建会话。' : !ready.value ? '助手尚未启用，当前不能发送问题。'
  : '仅查询本人或公开校园信息；正文按保留期限清理。')
const stateLabel = (state: string) => ({ active: '对话中', archived: '已归档', expired: '已过期' }[state] ?? '不可用')
function amount(value: string | undefined) {
  if (!value || !/^\d+(?:\.\d{1,8})?$/.test(value)) return '—'
  const [whole, decimals = ''] = value.split('.')
  const fraction = decimals.replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : whole
}

function send() { void messageList.value?.scrollToLatest(); void chat.submit() }
async function removeConversation() {
  try {
    await ElMessageBox.confirm('删除后会话正文立即清除，无法恢复。确定删除当前会话？', '删除会话', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '保留' })
    await chat.changeConversation(true)
  } catch { /* A cancelled confirmation makes no request. */ }
}
</script>

<template>
  <section class="assistant-page">
    <div class="campus-page-heading campus-heading-with-action"><div><p class="campus-eyebrow">CAMPUS ASSISTANT</p><h1>校园助手</h1><p>连接校园信息，在同一会话里继续提问。</p></div><el-button :loading="loading" :disabled="submitting || changing" @click="chat.reload">刷新状态</el-button></div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="assistant-page-alert" />
    <el-alert v-if="budgetError" :title="`助手状态暂不可用：${budgetError}`" type="warning" show-icon :closable="false" class="assistant-page-alert" />
    <el-alert v-else-if="budget && !ready" title="助手尚未启用：当前可以管理历史会话，暂不能发送问题。校园数据外发保持关闭。" type="info" show-icon :closable="false" class="assistant-page-alert" />
    <div class="assistant-workspace">
      <aside class="assistant-conversations" aria-label="会话列表">
        <div class="assistant-conversations-heading"><h2>我的会话</h2><el-button size="small" type="primary" plain :loading="changing" :disabled="submitting || loadingMessages" @click="chat.newConversation">＋ 新建</el-button></div>
        <p class="assistant-sidebar-caption">会话内容仅本人可见</p>
        <div class="assistant-conversation-list"><button v-for="conversation in conversations" :key="conversation.id" type="button" class="assistant-conversation" :class="{ selected: selected?.id === conversation.id }" :aria-current="selected?.id === conversation.id ? 'true' : undefined" :disabled="changing" @click="chat.selectConversation(conversation.id)"><span class="assistant-conversation-title">{{ conversation.title }}</span><span class="assistant-conversation-meta">{{ conversation.active_run_id ? '有运行正在处理' : stateLabel(conversation.state) }}</span></button><p v-if="!loading && !conversations.length" class="assistant-sidebar-empty">还没有会话<br>新建会话，开始提问</p><el-button v-if="conversations.length < conversationTotal" text :loading="loading" @click="chat.loadMoreConversations">加载更多会话</el-button></div>
        <div v-if="budget" class="assistant-budget"><strong>今日用量 · {{ budget.day }}</strong><dl><div><dt>估算消费</dt><dd>¥ {{ amount(budget.user.spent) }}</dd></div><div><dt>在途预留</dt><dd>¥ {{ amount(budget.user.reserved) }}</dd></div><div><dt>可用额度</dt><dd>¥ {{ amount(budget.user.available) }}</dd></div></dl><p>单次上限 ¥ {{ amount(budget.policy.run_cost_limit) }}<br>正文保留 {{ budget.policy.retention_days }} 天</p></div>
      </aside>
      <section class="assistant-chat" aria-label="助手对话">
        <header class="assistant-chat-header"><div><h2>{{ selected?.title || '选择一段对话' }}</h2><p>{{ selected ? stateLabel(selected.state) : '新建会话后开始' }}<template v-if="activeRun"> · 本次估算 ¥ {{ amount(activeRun.spent) }}</template></p></div><div v-if="selected" class="assistant-conversation-actions"><el-button v-if="selected.state === 'active' || selected.state === 'archived'" text size="small" :disabled="running || receiving || submitting || changing || Boolean(pending)" @click="chat.changeConversation()">{{ selected.state === 'archived' ? '恢复会话' : '归档' }}</el-button><el-button text type="danger" size="small" :disabled="running || receiving || submitting || changing || Boolean(pending)" @click="removeConversation">删除</el-button></div></header>
        <AssistantMessages ref="messageList" :conversation-id="selected?.id ?? null" :messages="messages" :partial="partial" :loading="loadingMessages" :loading-older="loadingOlder" :can-load-older="canLoadOlder" :status="statusText" @older="chat.loadOlder" />
        <div v-if="streamError || sendError || (activeRun && ['failed', 'cancelled', 'expired'].includes(activeRun.status))" class="assistant-feedback" role="status"><p v-if="sendError">{{ sendError }}</p><p v-if="pending">提交结果尚未确认。请使用原请求确认，避免重复发送。</p><el-button v-if="pending" size="small" :loading="submitting" @click="chat.submit(true)">确认原提交结果</el-button><p v-if="streamError">{{ streamError }}</p><el-button v-if="connection === 'interrupted' && activeRun" size="small" @click="chat.reconnectRun">重新连接原运行</el-button><p v-if="activeRun && ['failed', 'cancelled', 'expired'].includes(activeRun.status)">{{ runReason(activeRun.reason) }}</p></div>
        <AssistantComposer v-model="input" :disabled="!selected || selected.state !== 'active' || !ready || submitting || loadingMessages || Boolean(pending)" :can-send="canSend" :submitting="submitting" :running="running" :cancelling="cancelling" :hint="composerHint" @send="send" @stop="chat.cancel" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.assistant-page { max-width: 1350px; }.assistant-page-alert { margin-bottom: 16px; }.assistant-workspace { display: grid; grid-template-columns: 215px minmax(0, 1fr); min-height: 570px; height: min(750px, 76vh); border: 1px solid #e5eaf4; border-radius: 15px; background: #fff; overflow: hidden; box-shadow: 0 5px 25px #1c315f04; }.assistant-conversations { display: flex; flex-direction: column; min-height: 0; background: #fafbfe; border-right: 1px solid #e9edf5; padding: 22px 14px 17px; }.assistant-conversations-heading { display: flex; align-items: center; justify-content: space-between; gap: 9px; }.assistant-conversations-heading h2 { font-size: 14px; margin: 0; color: #40536e; }.assistant-sidebar-caption { color: #9aa7b8; font-size: 11px; margin: 13px 0 15px; }.assistant-conversation-list { min-height: 100px; overflow-y: auto; flex: 1; padding-bottom: 14px; }.assistant-conversation { display: flex; flex-direction: column; gap: 8px; width: 100%; padding: 13px 12px; text-align: left; border: 1px solid transparent; border-radius: 9px; background: none; cursor: pointer; margin-bottom: 5px; font: inherit; }.assistant-conversation:hover { background: #f0f3fb; }.assistant-conversation.selected { background: #edf0ff; border-color: #e0e5fb; }.assistant-conversation-title { color: #53657f; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }.assistant-conversation-meta { font-size: 10px; color: #9aa5b7; }.assistant-sidebar-empty { font-size: 12px; color: #99a6b8; line-height: 2; margin-top: 30px; text-align: center; }.assistant-budget { font-size: 11px; border-top: 1px solid #e8edf5; color: #96a3b6; padding: 17px 8px 0; }.assistant-budget strong { font-weight: 500; color: #7c8aa0; }.assistant-budget dl { margin: 15px 0; }.assistant-budget dl div { display: flex; justify-content: space-between; gap: 6px; margin-bottom: 9px; }.assistant-budget dt, .assistant-budget dd { margin: 0; }.assistant-budget dd { color: #667b98; font-variant-numeric: tabular-nums; }.assistant-budget p { margin: 0; line-height: 1.9; }
.assistant-chat { display: flex; flex-direction: column; min-height: 0; min-width: 0; }.assistant-chat-header { padding: 19px 24px; border-bottom: 1px solid #edf0f6; display: flex; justify-content: space-between; align-items: center; gap: 12px; }.assistant-chat-header h2 { font-size: 15px; color: #3f536f; margin: 0 0 6px; overflow-wrap: anywhere; }.assistant-chat-header p { margin: 0; color: #9ba6b7; font-size: 11px; }.assistant-conversation-actions { flex-shrink: 0; display: flex; gap: 1px; }.assistant-feedback { padding: 10px 23px; background: #fffbf3; color: #9c7a42; border-top: 1px solid #f1e8d8; font-size: 12px; line-height: 1.7; }.assistant-feedback p { margin: 3px 0; }.assistant-feedback .el-button { margin: 5px 0; }
@media (max-width: 1060px) { .assistant-workspace { grid-template-columns: 180px minmax(0, 1fr); }.assistant-conversations { padding-right: 10px; padding-left: 10px; } }
@media (max-width: 760px) { .assistant-workspace { display: flex; flex-direction: column; height: 790px; max-height: none; min-height: 630px; }.assistant-conversations { padding: 13px 14px; border-right: 0; border-bottom: 1px solid #e9edf5; max-height: 168px; flex-shrink: 0; }.assistant-conversations-heading h2 { font-size: 12px; }.assistant-sidebar-caption, .assistant-budget { display: none; }.assistant-conversation-list { display: flex; flex-direction: row; gap: 8px; overflow-x: auto; min-height: 0; padding-bottom: 0; margin-top: 11px; }.assistant-conversation { flex: 0 0 155px; margin-bottom: 0; padding: 9px 11px; }.assistant-sidebar-empty { margin: 0; text-align: left; }.assistant-chat { flex: 1; }.assistant-chat-header { padding: 15px; }.assistant-chat-header h2 { font-size: 13px; }.assistant-feedback { padding: 10px 15px; } }
</style>
