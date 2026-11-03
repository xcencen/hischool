<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { adminAssistantAccessApi, setAssistantAccessApi, assistantOperationsApi } from '../api/assistant'
import type { AssistantAccessUser, AssistantOperations } from '../api/assistant'
import { token } from '../utils/campus-auth'
import { readToken } from '../utils/session-storage'
import { errorMessage } from '../utils/campus-request'

const rows = ref<AssistantAccessUser[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const pending = ref<number | null>(null)
const error = ref('')
const operations = ref<AssistantOperations | null>(null)
const operationsError = ref('')
const controller = new AbortController()
const session = token.value
let generation = 0
let alive = true
const valid = () => alive && token.value === session && readToken() === session && !controller.signal.aborted
async function loadAccess() {
  const current = ++generation
  loading.value = true; rows.value = []
  try {
    const data = await adminAssistantAccessApi(page.value, controller.signal)
    if (!valid() || current !== generation) return
    rows.value = data.list; total.value = data.total
  } catch (cause) { if (valid() && current === generation) error.value = errorMessage(cause) }
  finally { if (valid() && current === generation) loading.value = false }
}
async function loadOperations() {
  operations.value = null; operationsError.value = ''
  try {
    const data = await assistantOperationsApi(controller.signal)
    if (valid()) operations.value = data
  } catch (cause) { if (valid()) operationsError.value = errorMessage(cause) }
}
async function refresh() { if (loading.value || pending.value !== null) return; error.value = ''; await Promise.all([loadAccess(), loadOperations()]) }
async function change(item: AssistantAccessUser) {
  if (pending.value !== null || loading.value || !valid()) return
  pending.value = item.user_id; error.value = ''
  try {
    const data = await setAssistantAccessApi(item, controller.signal)
    if (!valid()) return
    rows.value = rows.value.map(row => row.user_id === data.user_id ? data : row)
  } catch (cause) {
    if (!valid()) return
    error.value = errorMessage(cause)
    // Refresh the server generation; never replay the rejected mutation.
    await loadAccess()
  } finally { if (valid()) pending.value = null }
}
function clear() { ++generation; controller.abort(); rows.value = []; total.value = 0; operations.value = null; error.value = ''; operationsError.value = '' }
watch(token, clear)
onMounted(refresh)
onBeforeUnmount(() => { alive = false; clear() })
const warnings: Record<string, string> = { queued_overdue: '排队超期', expired_leases: '运行租约过期', terminal_reserved: '终态仍有预留', cleanup_overdue: '正文清理超期', model_usage_unknown: '模型未知用量' }
const age = (value: number | null) => value === null ? '—' : `${value} 秒`
</script>

<template>
  <section class="admin-assistant">
    <div class="campus-page-heading campus-heading-with-action"><div><h1>助手管理</h1><p>管理指定账号资格与本地运行状态。授予资格后仍需本人确认当前告知。</p></div><el-button :disabled="loading || pending !== null" @click="refresh">刷新状态</el-button></div>
    <p v-if="error" role="alert">{{ error }}</p>
    <h2>指定账号资格</h2>
    <el-table :data="rows" v-loading="loading" empty-text="暂无可显示账号">
      <el-table-column prop="username" label="账号" /><el-table-column prop="name" label="姓名" />
      <el-table-column label="资格"><template #default="{ row }">{{ row.eligible ? '已授权' : '未授权' }}</template></el-table-column>
      <el-table-column prop="generation" label="代次" />
      <el-table-column label="操作" min-width="120"><template #default="{ row }"><el-button :disabled="loading || pending !== null" @click="change(row)">{{ row.eligible ? '撤销资格' : '授予资格' }}</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" :disabled="loading || pending !== null" @current-change="loadAccess" />
    <h2>运行状态</h2>
    <p v-if="operationsError" role="alert">无法评估：{{ operationsError }}</p>
    <template v-if="operations">
      <p role="status">{{ operations.status === 'ok' ? '正常' : '需处理' }} · 检查时间 {{ operations.checked_at }} · 超期告警阈值 {{ operations.warning_after_s }} 秒</p>
      <ul aria-label="运行告警"><li v-for="warning in operations.warnings" :key="warning">{{ warnings[warning] || '其他运行告警' }}</li></ul>
      <dl class="operation-counts">
        <div><dt>排队</dt><dd>{{ operations.queued.count }} 项 · 最久 {{ age(operations.queued.oldest_age_s) }} · 超期 {{ operations.queued.overdue_count }} 项 · 最久超期 {{ age(operations.queued.oldest_overdue_s) }}</dd></div>
        <div><dt>过期租约</dt><dd>{{ operations.expired_leases.count }} 项 · 最久 {{ age(operations.expired_leases.oldest_age_s) }}</dd></div>
        <div><dt>终态预留</dt><dd>{{ operations.terminal_reserved.count }} 项 · 最久 {{ age(operations.terminal_reserved.oldest_age_s) }}</dd></div>
        <div><dt>正文清理待处理</dt><dd>{{ operations.cleanup.count }} 项 · 最久 {{ age(operations.cleanup.oldest_age_s) }}</dd></div>
        <div><dt>模型未知费用</dt><dd>{{ operations.costs.model_unknown_count }} 项 · 保守计费 ¥ {{ operations.costs.model_unknown_charged }}</dd></div>
        <div><dt>嵌入上界计费</dt><dd>{{ operations.costs.embedding_conservative_count }} 项 · ¥ {{ operations.costs.embedding_conservative_charged }}</dd></div>
      </dl>
      <h3>失败原因汇总</h3><ul><li v-for="item in operations.failed_reasons" :key="item.reason">{{ item.reason }}：{{ item.count }}</li></ul>
    </template>
  </section>
</template>
<style scoped>
.admin-assistant { max-width: 1150px; overflow-wrap: anywhere; }.admin-assistant h2 { margin-top: 26px; font-size: 18px; }.operation-counts div { padding: 12px; border-bottom: 1px solid #e5eaf4; }.operation-counts dt { font-weight: 600; }.operation-counts dd { margin: 6px 0 0; }.admin-assistant [role=alert] { padding: 12px; background: #fff4ef; color: #963d23; }
</style>
