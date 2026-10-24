<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { activitiesApi } from '../api/community'
import type { Activity } from '../api/community'
import { displayDateTime } from '../utils/campus-date'
import { errorMessage } from '../utils/campus-request'
const rows = ref<Activity[]>([])
const q = ref('')
const page = ref(1)
const total = ref(0)
const error = ref('')
const loading = ref(false)
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  try { const data = await activitiesApi({ page: page.value, page_size: 9, q: q.value.trim() }); if (id === sequence) { rows.value = data.list; total.value = data.total } }
  catch (cause) { if (id === sequence) { rows.value = []; error.value = errorMessage(cause) } }
  finally { if (id === sequence) loading.value = false }
}
function search() { page.value = 1; void load() }
onMounted(load)
</script>
<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">CAMPUS EVENTS</p><h1>校园活动</h1><p>发现校园活动，查看详情并在线报名。</p></div>
    <form class="campus-table-toolbar" @submit.prevent="search"><el-input v-model="q" placeholder="搜索活动标题或介绍" maxlength="100" clearable aria-label="搜索活动" /><el-button type="primary" native-type="submit" :loading="loading">搜索</el-button></form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="campus-spaced" />
    <div v-loading="loading" class="campus-course-list">
      <router-link v-for="activity in rows" :key="activity.id" :to="`/app/activities/${activity.id}`" class="campus-course-card campus-event-card"><el-tag :type="activity.can_register ? 'success' : 'info'" effect="plain" size="small">{{ activity.can_register ? '报名开放' : activity.enrolled_count >= activity.capacity ? '名额已满' : '报名已截止' }}</el-tag><h2>{{ activity.title }}</h2><p class="campus-muted">{{ displayDateTime(activity.start_time) }}</p><p class="campus-muted">{{ activity.location }}</p><p class="campus-excerpt">{{ activity.content }}</p><div class="campus-event-footer"><span class="campus-muted campus-small">剩余 {{ activity.capacity - activity.enrolled_count }} / {{ activity.capacity }} 名额</span><span class="campus-card-link">查看活动 →</span></div></router-link>
    </div>
    <el-empty v-if="!loading && !error && !rows.length" description="暂无符合条件的活动" />
    <el-pagination v-if="total > 9" v-model:current-page="page" :total="total" :page-size="9" layout="prev, pager, next" class="campus-pagination" @current-change="load" />
  </section>
</template>
