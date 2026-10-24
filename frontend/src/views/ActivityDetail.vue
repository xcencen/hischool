<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { activityApi, registerActivityApi, cancelActivityApi } from '../api/community'
import type { Activity } from '../api/community'
import { displayDateTime } from '../utils/campus-date'
import { errorMessage } from '../utils/campus-request'
const route = useRoute()
const activity = ref<Activity | null>(null)
const error = ref('')
const actionError = ref('')
const loading = ref(false)
const saving = ref(false)
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  activity.value = null
  try { const data = await activityApi(Number(route.params.id)); if (id === sequence) activity.value = data }
  catch (cause) { if (id === sequence) error.value = errorMessage(cause) }
  finally { if (id === sequence) loading.value = false }
}
async function decide(cancel: boolean) {
  const value = activity.value
  if (!value) return
  try { await ElMessageBox.confirm(`确认${cancel ? '取消报名' : '报名'}“${value.title}”？`, cancel ? '取消报名' : '活动报名', { confirmButtonText: '确认', cancelButtonText: '返回' }) }
  catch { return }
  saving.value = true
  actionError.value = ''
  try {
    if (cancel) await cancelActivityApi(value.id)
    else await registerActivityApi(value.id)
    ElMessage.success(cancel ? '已取消报名，名额已恢复' : '报名成功')
    await load()
  } catch (cause) { actionError.value = errorMessage(cause); await load() }
  finally { saving.value = false }
}
watch(() => route.params.id, load, { immediate: true })
</script>
<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">EVENT DETAILS</p><h1>活动详情</h1><router-link to="/app/activities" class="campus-card-link">← 返回校园活动</router-link></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon><el-button text @click="load">重新加载</el-button></el-alert>
    <article v-else v-loading="loading" class="campus-table-card campus-article"><template v-if="activity">
      <el-tag effect="plain">{{ activity.registration_status === 'registered' ? '已报名' : activity.can_register ? '报名开放' : '报名已截止或名额已满' }}</el-tag><h2>{{ activity.title }}</h2><p class="campus-muted">发布人：{{ activity.publisher_name }}</p>
      <el-descriptions :column="1" class="campus-spaced"><el-descriptions-item label="开始时间">{{ displayDateTime(activity.start_time) }}</el-descriptions-item><el-descriptions-item label="结束时间">{{ displayDateTime(activity.end_time) }}</el-descriptions-item><el-descriptions-item label="报名截止">{{ displayDateTime(activity.registration_deadline) }}</el-descriptions-item><el-descriptions-item label="活动地点">{{ activity.location }}</el-descriptions-item><el-descriptions-item label="活动名额">{{ activity.enrolled_count }} / {{ activity.capacity }} 人</el-descriptions-item></el-descriptions>
      <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon class="campus-spaced" />
      <div class="campus-event-actions"><el-button v-if="activity.registration_status !== 'registered'" type="primary" :disabled="!activity.can_register" :loading="saving" @click="decide(false)">报名参加</el-button><el-button v-else :disabled="!activity.can_cancel" :loading="saving" @click="decide(true)">取消报名</el-button><router-link to="/app/registrations" class="campus-card-link">我的报名记录 →</router-link></div>
      <p class="campus-muted campus-small">活动开始前可取消报名；所有时间按北京时间展示。</p><div class="campus-article-text">{{ activity.content }}</div>
    </template></article>
  </section>
</template>
