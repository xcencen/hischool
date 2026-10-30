<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { AssistantMessage, Citation } from '../../api/assistant'
import { citationPath } from '../../utils/assistant-events'
import { fetchKnowledgeSource } from '../../api/knowledge'
import { errorMessage } from '../../utils/campus-request'
import { readToken } from '../../utils/session-storage'

const props = defineProps<{ conversationId: string | null; messages: AssistantMessage[]; partial: string;
  loading: boolean; loadingOlder: boolean; canLoadOlder: boolean; status: string }>()
const emit = defineEmits<{ older: [] }>()
const viewport = ref<HTMLElement | null>(null)
const nearBottom = ref(true)
const openingSource = ref<string | null>(null)
let alive = true
let oldHeight = 0
let oldTop = 0
let historyAnchor = false
let sourceGeneration = 0
const sourceCleanups = new Set<() => void>()
function closeSources() { ++sourceGeneration; for (const close of sourceCleanups) close(); openingSource.value = null }

function onScroll() {
  const element = viewport.value
  if (element) nearBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 90
}
async function scrollToLatest() {
  nearBottom.value = true
  await nextTick()
  if (viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight
}
watch(() => props.conversationId, () => { closeSources(); nearBottom.value = true; historyAnchor = false; void scrollToLatest() })
watch(() => props.messages, messages => {
  if (!messages.some(message => !message.redacted && message.citations.length)) closeSources()
})
watch(() => props.loadingOlder, async loading => {
  const element = viewport.value
  if (!element) return
  if (loading) { oldHeight = element.scrollHeight; oldTop = element.scrollTop; historyAnchor = true }
  else {
    await nextTick()
    element.scrollTop = oldTop + element.scrollHeight - oldHeight
    historyAnchor = false; onScroll()
  }
})
watch(() => [props.messages.length, props.partial, props.status, props.loading], async () => {
  if (historyAnchor) return
  if (nearBottom.value) await scrollToLatest()
}, { flush: 'post' })

async function openSource(citation: Citation) {
  if (openingSource.value || citation.kind !== 'knowledge' || !citationPath(citation) || !citation.version) return
  const popup = window.open('', '_blank')
  if (!popup) { ElMessage.warning('请允许弹窗后查看原文。'); return }
  const generation = sourceGeneration
  const expectedToken = readToken()
  let url = ''
  let watcher = 0
  let expiry = 0
  const release = () => {
    if (url) URL.revokeObjectURL(url)
    window.clearInterval(watcher); window.clearTimeout(expiry); popup.close(); sourceCleanups.delete(release)
  }
  sourceCleanups.add(release)
  popup.opener = null; popup.document.title = '正在加载知识原文'; popup.document.body.textContent = '正在加载原文，请稍候…'
  openingSource.value = citation.source_id
  try {
    const source = await fetchKnowledgeSource(citation.item_id, citation.version)
    if (!alive || popup.closed || generation !== sourceGeneration || expectedToken !== readToken()) { release(); return }
    url = URL.createObjectURL(source)
    popup.location.replace(`${url}#page=${citation.page_number}`)
    watcher = window.setInterval(() => { if (popup.closed) release() }, 10000)
    expiry = window.setTimeout(release, 300000)
  } catch (cause) { release(); if (alive && generation === sourceGeneration && expectedToken === readToken()) ElMessage.error(errorMessage(cause)) }
  finally { if (alive && generation === sourceGeneration) openingSource.value = null }
}
onBeforeUnmount(() => { alive = false; closeSources() })
defineExpose({ scrollToLatest })
</script>

<template>
  <div class="assistant-message-region">
    <div ref="viewport" class="assistant-message-scroll" role="log" aria-label="对话消息" aria-live="polite" :aria-busy="loading" @scroll.passive="onScroll">
      <div v-if="canLoadOlder" class="assistant-history-action"><el-button text :loading="loadingOlder" @click="emit('older')">加载更早消息</el-button></div>
      <div v-if="loading" class="assistant-message-empty" role="status">正在加载会话历史…</div>
      <div v-else-if="!messages.length && !partial" class="assistant-message-empty"><span class="assistant-empty-symbol">m</span><h3>开始一段校园对话</h3><p>查询课表、公开通知、活动或学生手册。历史上下文由服务端维护。</p><p class="assistant-small">助手仅提供只读查询，请核对来源和实际业务页面。</p></div>
      <article v-for="message in messages" :key="message.id" class="assistant-message" :class="`assistant-message-${message.role}`">
        <div class="assistant-message-avatar" aria-hidden="true">{{ message.role === 'user' ? '我' : 'm' }}</div>
        <div class="assistant-message-body"><div class="assistant-message-meta"><strong>{{ message.role === 'user' ? '你' : '校园助手' }}</strong><span v-if="message.redacted">已过期</span></div>
          <div class="assistant-message-text" :class="{ 'assistant-message-redacted': message.redacted }">{{ message.redacted || message.content === null ? '正文已按保留期限清除。' : message.content }}</div>
          <ul v-if="!message.redacted && message.citations.length" class="assistant-citations" aria-label="回答来源">
            <li v-for="citation in message.citations" :key="citation.source_id">
              <template v-if="citationPath(citation)"><el-button v-if="citation.kind === 'knowledge'" link type="primary" :loading="openingSource === citation.source_id" :disabled="openingSource !== null" @click="openSource(citation)">[{{ citation.source_id }}] {{ citation.title }} · 第 {{ citation.page_number }} 页 ↗</el-button><router-link v-else :to="citationPath(citation)!">[{{ citation.source_id }}] {{ citation.title }} ↗</router-link></template>
              <span v-else>[{{ citation.source_id }}] 来源暂不可用</span>
            </li>
          </ul>
        </div>
      </article>
      <article v-if="partial" class="assistant-message assistant-message-assistant"><div class="assistant-message-avatar" aria-hidden="true">m</div><div class="assistant-message-body"><div class="assistant-message-meta"><strong>校园助手</strong><span>正在接收已完成的回复</span></div><div class="assistant-message-text">{{ partial }}<span class="assistant-cursor" aria-hidden="true">▍</span></div></div></article>
      <p v-if="status && !partial" class="assistant-runtime-status" role="status"><span class="assistant-loading-dot" aria-hidden="true" />{{ status }}</p>
    </div>
    <el-button v-if="!nearBottom" class="assistant-latest" size="small" @click="scrollToLatest">回到最新消息 ↓</el-button>
  </div>
</template>

<style scoped>
.assistant-message-region { position: relative; min-height: 0; flex: 1; }
.assistant-message-scroll { height: 100%; overflow-y: auto; overscroll-behavior: contain; padding: 24px 28px 34px; box-sizing: border-box; scroll-behavior: auto; }
.assistant-history-action { text-align: center; margin-bottom: 15px; }
.assistant-message-empty { min-height: 210px; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; color: #8795ab; gap: 10px; padding: 24px 10px; }
.assistant-message-empty h3 { color: #34445e; font-size: 18px; margin: 8px 0 0; }.assistant-message-empty p { margin: 0; line-height: 1.8; max-width: 430px; font-size: 13px; }
.assistant-empty-symbol { width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; background: #edf0ff; color: #6679d7; font-size: 30px; font-weight: 700; }
.assistant-message { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 27px; }.assistant-message-avatar { flex: 0 0 30px; height: 30px; display: grid; place-items: center; border-radius: 9px; background: #e9edff; color: #6674ca; font-size: 19px; font-weight: 650; }
.assistant-message-user .assistant-message-avatar { background: #eef2f7; color: #72839c; font-size: 12px; }.assistant-message-body { min-width: 0; flex: 1; }.assistant-message-meta { display: flex; align-items: center; gap: 10px; margin: 4px 0 10px; font-size: 12px; color: #9ba5b5; }.assistant-message-meta strong { color: #52647f; font-size: 13px; }
.assistant-message-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.95; font-size: 14px; color: #425571; }.assistant-message-user .assistant-message-text { border: 1px solid #edf0f6; border-radius: 0 13px 13px; background: #f8faff; padding: 12px 16px; }.assistant-message-redacted { color: #9ba7b8; font-style: italic; }
.assistant-citations { list-style: none; padding: 10px 0 0; margin: 10px 0 0; border-top: 1px solid #edf0f7; }.assistant-citations li { margin-top: 7px; font-size: 12px; overflow-wrap: anywhere; }.assistant-citations a { color: #596ec7; text-decoration: none; }.assistant-citations :deep(.el-button) { white-space: normal; height: auto; text-align: left; line-height: 1.7; font-size: 12px; }
.assistant-runtime-status { display: flex; align-items: center; gap: 9px; color: #8a98ad; font-size: 12px; margin: 20px 0; }.assistant-loading-dot { width: 7px; height: 7px; border-radius: 50%; background: #7788d6; animation: assistant-pulse 1.4s ease-in-out infinite; }.assistant-cursor { color: #7a88d3; animation: assistant-pulse 1s infinite; }.assistant-latest { position: absolute; bottom: 14px; right: 22px; box-shadow: 0 3px 15px #27395b15; }
.assistant-small { font-size: 12px !important; }
@keyframes assistant-pulse { 50% { opacity: .3; } }@media (prefers-reduced-motion: reduce) { .assistant-loading-dot, .assistant-cursor { animation: none; } }
@media (max-width: 760px) { .assistant-message-scroll { padding: 20px 15px; }.assistant-message { gap: 9px; }.assistant-message-meta { flex-wrap: wrap; gap: 5px; }.assistant-message-text { font-size: 13px; } }
</style>
