<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchKnowledgeSource, knowledgeDocumentsApi, knowledgeSearchApi, knowledgeStatusApi } from '../api/knowledge'
import type { KnowledgeDocument, KnowledgeHit, KnowledgeSearchResult, KnowledgeStatus } from '../api/knowledge'
import { errorMessage } from '../utils/campus-request'

const status = ref<KnowledgeStatus | null>(null)
const documents = ref<KnowledgeDocument[]>([])
const metadataLoading = ref(false)
const statusError = ref('')
const documentsError = ref('')
const query = ref('')
const topK = ref(5)
const searching = ref(false)
const searchError = ref('')
const result = ref<KnowledgeSearchResult | null>(null)
const openingSource = ref<string | null>(null)
const searchReady = computed(() => Boolean(status.value?.configured && status.value.ready && !metadataLoading.value))
const stateTitle = computed(() => !status.value?.configured ? '知识检索服务待配置' : status.value.ready ? '知识检索已就绪' : '知识索引尚未就绪')
let metadataSequence = 0
let searchSequence = 0
let alive = true

const categoryLabel = (category: KnowledgeDocument['category']) =>
  ({ faq: '校园 FAQ', regulations: '校规制度', guide: '办事指南' }[category])

function documentStatus(value: string): string {
  return ({ ready: '可检索', pending: '等待处理', parsed: '已解析', queued: '等待入库', processing: '处理中', embedded: '待建索引', failed: '处理失败' }[value] ?? '处理中')
}

function scoreLabel(score: number): string {
  return Number.isFinite(score) ? score.toFixed(3) : '—'
}

async function reload() {
  const sequence = ++metadataSequence
  ++searchSequence
  searching.value = false
  result.value = null
  searchError.value = ''
  metadataLoading.value = true
  statusError.value = documentsError.value = ''
  const [state, sources] = await Promise.allSettled([knowledgeStatusApi(), knowledgeDocumentsApi()])
  if (!alive || sequence !== metadataSequence) return
  if (state.status === 'fulfilled') status.value = state.value
  else { status.value = null; statusError.value = errorMessage(state.reason) }
  if (sources.status === 'fulfilled') documents.value = sources.value
  else { documents.value = []; documentsError.value = errorMessage(sources.reason) }
  metadataLoading.value = false
}

async function search() {
  if (!searchReady.value || searching.value) return
  const value = query.value.trim()
  if (!value) { ElMessage.warning('请输入要查找的问题。'); return }
  const sequence = ++searchSequence
  searching.value = true
  searchError.value = ''
  result.value = null
  const limit = Number.isInteger(topK.value) ? Math.max(1, Math.min(10, topK.value)) : 5
  try {
    const data = await knowledgeSearchApi(value, limit)
    if (alive && sequence === searchSequence) result.value = data
  } catch (error) {
    if (alive && sequence === searchSequence) searchError.value = errorMessage(error)
  } finally {
    if (alive && sequence === searchSequence) searching.value = false
  }
}

async function openSource(hit: Pick<KnowledgeHit, 'document_id' | 'version' | 'page_number'>) {
  if (openingSource.value) return
  const popup = window.open('', '_blank')
  if (!popup) { ElMessage.warning('浏览器拦截了原文窗口，请允许弹窗后重试。'); return }
  popup.opener = null
  popup.document.title = '正在加载知识原文'
  popup.document.body.textContent = '正在加载原文，请稍候…'
  openingSource.value = `${hit.document_id}:${hit.version}`
  try {
    const source = await fetchKnowledgeSource(hit.document_id, hit.version)
    if (!alive || popup.closed) { popup.close(); return }
    const url = URL.createObjectURL(source)
    const page = Number.isSafeInteger(hit.page_number) && hit.page_number > 0 ? hit.page_number : 1
    popup.location.replace(`${url}#page=${page}`)
    // Keep the source usable after leaving this Vue page; release it when the
    // opened tab closes, with an upper bound for abandoned tabs.
    const release = () => { URL.revokeObjectURL(url); window.clearInterval(watcher); window.clearTimeout(expiry) }
    const watcher = window.setInterval(() => { if (popup.closed) release() }, 10000)
    const expiry = window.setTimeout(release, 300000)
  } catch (error) {
    popup.close()
    if (alive) ElMessage.error(errorMessage(error))
  } finally {
    if (alive) openingSource.value = null
  }
}

onMounted(reload)
onBeforeUnmount(() => { alive = false; ++metadataSequence; ++searchSequence })
</script>

<template>
  <section>
    <div class="campus-page-heading campus-heading-with-action">
      <div><p class="campus-eyebrow">CAMPUS KNOWLEDGE</p><h1>校园知识检索</h1><p>从已导入资料中查找相关原文，并核对章节和页码出处。</p></div>
      <el-button :loading="metadataLoading" @click="reload">刷新状态</el-button>
    </div>

    <el-alert v-if="statusError" :title="statusError" type="error" show-icon :closable="false" class="campus-spaced" />
    <div v-loading="metadataLoading" class="campus-table-card knowledge-search-card">
      <div v-if="status" class="knowledge-status">
        <el-tag :type="searchReady ? 'success' : 'warning'" effect="plain">{{ stateTitle }}</el-tag>
        <span class="campus-muted">{{ status.document_count }} 份资料 · {{ status.chunk_count }} 个片段</span>
      </div>
      <el-alert v-if="status && !searchReady && !metadataLoading" :title="status.message || '资料或检索服务尚未准备完成，请稍后刷新状态。'" type="warning" show-icon :closable="false" class="campus-spaced" />
      <form @submit.prevent="search">
        <label class="knowledge-query-label" for="knowledge-query">想了解什么校园问题？</label>
        <el-input id="knowledge-query" v-model="query" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="输入问题或关键词，查找相关资料" :disabled="!searchReady" />
        <div class="knowledge-search-actions">
          <label class="knowledge-limit">检索条数 <el-input-number v-model="topK" :min="1" :max="10" :precision="0" size="small" aria-label="检索条数" :disabled="!searchReady || searching" /></label>
          <el-button type="primary" native-type="submit" :loading="searching" :disabled="!searchReady || !query.trim()">检索资料</el-button>
        </div>
      </form>
    </div>

    <el-alert v-if="searchError" :title="searchError" type="error" show-icon :closable="false" class="knowledge-result-error" />
    <section v-if="result" class="knowledge-results" aria-live="polite">
      <div class="knowledge-results-heading"><h2>检索结果</h2><span class="campus-muted">共 {{ result.results.length }} 个相关片段</span></div>
      <p class="campus-muted knowledge-searched-query">检索问题：{{ result.query }}</p>
      <el-alert v-if="result.insufficient" :title="result.message || '当前资料不足以支持这个问题，请核对原文或补充资料。'" type="warning" show-icon :closable="false" class="campus-spaced" />
      <el-empty v-if="!result.results.length" description="未找到可引用的相关资料" :image-size="80" />
      <article v-for="hit in result.results" :key="hit.chunk_id" class="campus-table-card knowledge-hit">
        <div class="knowledge-hit-heading"><h3>{{ hit.document_title }}</h3><el-tag size="small" effect="plain">相似度 {{ scoreLabel(hit.score) }}</el-tag></div>
        <p class="knowledge-citation">第 {{ hit.version }} 版 · 原文第 {{ hit.page_number }} 页<template v-if="hit.page_label"> · 印刷页码 {{ hit.page_label }}</template></p>
        <p v-if="hit.chapter" class="campus-muted knowledge-chapter">{{ hit.chapter }}</p>
        <blockquote class="knowledge-hit-content">{{ hit.content }}</blockquote>
        <el-button link type="primary" :loading="openingSource === `${hit.document_id}:${hit.version}`" :disabled="openingSource !== null && openingSource !== `${hit.document_id}:${hit.version}`" @click="openSource(hit)">查看原文第 {{ hit.page_number }} 页 ↗</el-button>
      </article>
      <p v-if="result.results.length" class="campus-muted campus-small">以上为资料原文片段，相似度用于排序；请结合出处和上下文核对。</p>
    </section>

    <section class="campus-table-card knowledge-documents">
      <div class="knowledge-results-heading"><h2>已导入资料</h2><span class="campus-muted">{{ documents.length }} 份</span></div>
      <el-alert v-if="documentsError" :title="documentsError" type="error" show-icon :closable="false" class="campus-spaced" />
      <el-empty v-if="!metadataLoading && !documentsError && !documents.length" description="暂无已导入资料" :image-size="60" />
      <el-collapse v-else>
        <el-collapse-item v-for="document in documents" :key="document.id" :name="document.id">
          <template #title><span class="knowledge-document-title">{{ document.title }}</span><el-tag size="small" effect="plain" :type="document.status === 'ready' ? 'success' : 'info'">{{ documentStatus(document.status) }}</el-tag></template>
          <p class="campus-muted">{{ categoryLabel(document.category) }} · 第 {{ document.version }} 版 · {{ document.page_count }} 页 · {{ document.chunk_count }} 个片段</p>
          <ul v-if="document.warnings.length" class="knowledge-warnings"><li v-for="(warning, index) in document.warnings" :key="index">{{ warning }}</li></ul>
          <p v-else class="campus-muted campus-small">暂无解析提示。</p>
          <el-button link type="primary" :loading="openingSource === `${document.id}:${document.version}`" :disabled="openingSource !== null && openingSource !== `${document.id}:${document.version}`" @click="openSource({ document_id: document.id, version: document.version, page_number: 1 })">查看资料原文 ↗</el-button>
        </el-collapse-item>
      </el-collapse>
    </section>
  </section>
</template>

<style scoped>
.knowledge-search-card { margin-bottom: 25px; }
.knowledge-status { display: flex; flex-wrap: wrap; align-items: center; gap: 13px; margin-bottom: 23px; }
.knowledge-query-label { display: block; margin-bottom: 12px; color: #60708c; font-size: 13px; }
.knowledge-search-actions { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px; margin-top: 20px; }
.knowledge-limit { display: flex; align-items: center; gap: 12px; color: #8a95a8; font-size: 12px; }
.knowledge-result-error { margin: 24px 0; }
.knowledge-results { margin: 30px 0; }
.knowledge-results-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 15px; }
.knowledge-results-heading h2 { font-size: 18px; }
.knowledge-searched-query { margin-bottom: 20px; overflow-wrap: anywhere; }
.knowledge-hit { margin-bottom: 18px; }
.knowledge-hit-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 13px; }
.knowledge-hit-heading h3 { margin: 0; color: #465873; font-size: 17px; line-height: 1.7; overflow-wrap: anywhere; }
.knowledge-citation { color: #8694b0; font-size: 12px; line-height: 1.8; }
.knowledge-chapter { margin-bottom: 10px; overflow-wrap: anywhere; }
.knowledge-hit-content { margin: 18px 0; padding: 15px 18px; border-left: 3px solid #d8dff7; border-radius: 0 8px 8px 0; background: #f8f9fd; color: #687b98; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 14px; line-height: 1.95; }
.knowledge-documents { margin-top: 25px; }
.knowledge-document-title { margin-right: 12px; color: #62738f; overflow-wrap: anywhere; }
.knowledge-warnings { margin: 12px 0; padding-left: 19px; color: #9a835b; font-size: 12px; line-height: 1.9; }
@media (max-width: 760px) {
  .knowledge-search-actions > .el-button { width: 100%; }
  .knowledge-hit-heading h3 { font-size: 16px; }
  .knowledge-hit-content { margin: 15px 0; padding: 13px 12px; font-size: 13px; }
  .knowledge-document-title { font-size: 12px; }
}
</style>
