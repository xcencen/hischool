<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { categoriesApi, noticesApi } from '../api/community'
import type { Category, Notice } from '../api/community'
import { errorMessage } from '../utils/campus-request'
import { displayDateTime } from '../utils/campus-date'
const rows = ref<Notice[]>([])
const categories = ref<Category[]>([])
const categoryId = ref<number>()
const q = ref('')
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const error = ref('')
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  try {
    const [result, options] = await Promise.all([noticesApi({ page: page.value, page_size: 10, q: q.value.trim(), category_id: categoryId.value }), categoriesApi()])
    if (id === sequence) { rows.value = result.list; total.value = result.total; categories.value = options }
  } catch (cause) { if (id === sequence) { rows.value = []; error.value = errorMessage(cause) } }
  finally { if (id === sequence) loading.value = false }
}
function search() { page.value = 1; void load() }
onMounted(load)
</script>
<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">CAMPUS NEWS</p><h1>校园通知</h1><p>查看已发布的校园消息与教学安排。</p></div>
    <div class="campus-table-card">
      <form class="campus-table-toolbar campus-filter-toolbar" @submit.prevent="search"><el-input v-model="q" placeholder="搜索通知标题或正文" maxlength="100" clearable aria-label="搜索通知" /><el-select v-model="categoryId" placeholder="全部分类" clearable aria-label="通知分类"><el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" /></el-select><el-button type="primary" native-type="submit" :loading="loading">搜索</el-button></form>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <div v-loading="loading" class="campus-news-list">
        <router-link v-for="notice in rows" :key="notice.id" :to="`/app/notices/${notice.id}`" class="campus-news-row"><div><el-tag size="small" effect="plain">{{ notice.category_name }}</el-tag><h2>{{ notice.title }}</h2><p class="campus-excerpt">{{ notice.content }}</p><p class="campus-muted campus-small">{{ notice.publisher_name }} · {{ displayDateTime(notice.published_at) }}</p></div><span class="campus-card-link">查看详情 →</span></router-link>
        <el-empty v-if="!loading && !error && !rows.length" description="暂无符合条件的通知" />
      </div>
      <el-pagination v-if="total > 10" v-model:current-page="page" :page-size="10" :total="total" layout="prev, pager, next" class="campus-pagination" @current-change="load" />
    </div>
  </section>
</template>
