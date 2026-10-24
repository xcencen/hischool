<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { noticeApi } from '../api/community'
import type { Notice } from '../api/community'
import { displayDateTime } from '../utils/campus-date'
import { errorMessage } from '../utils/campus-request'
const route = useRoute()
const notice = ref<Notice | null>(null)
const error = ref('')
const loading = ref(false)
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  notice.value = null
  try { const data = await noticeApi(Number(route.params.id)); if (id === sequence) notice.value = data }
  catch (cause) { if (id === sequence) error.value = errorMessage(cause) }
  finally { if (id === sequence) loading.value = false }
}
watch(() => route.params.id, load, { immediate: true })
</script>
<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">NOTICE DETAILS</p><h1>通知详情</h1><router-link to="/app/notices" class="campus-card-link">← 返回校园通知</router-link></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon><el-button text @click="load">重新加载</el-button></el-alert>
    <article v-else v-loading="loading" class="campus-table-card campus-article"><template v-if="notice"><el-tag effect="plain">{{ notice.category_name }}</el-tag><h2>{{ notice.title }}</h2><p class="campus-muted">{{ notice.publisher_name }} · {{ displayDateTime(notice.published_at) }}</p><div class="campus-article-text">{{ notice.content }}</div></template></article>
  </section>
</template>
