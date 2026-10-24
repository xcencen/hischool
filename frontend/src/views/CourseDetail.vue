<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { courseDetailApi } from '../api/courses'
import type { Course } from '../api/courses'
import { errorMessage } from '../utils/campus-request'

const route = useRoute()
const course = ref<Course | null>(null)
const loading = ref(false)
const error = ref('')
let sequence = 0
async function load() {
  const requestId = ++sequence
  course.value = null
  error.value = ''
  const id = Number(route.params.id)
  if (!Number.isSafeInteger(id) || id < 1) { error.value = '课程编号无效'; return }
  loading.value = true
  try { const data = await courseDetailApi(id); if (requestId === sequence) course.value = data }
  catch (cause) { if (requestId === sequence) error.value = errorMessage(cause) }
  finally { if (requestId === sequence) loading.value = false }
}
watch(() => route.params.id, load, { immediate: true })
</script>

<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">COURSE DETAILS</p><h1>课程详情</h1><p><router-link class="campus-card-link" to="/app/courses">← 返回校园课程</router-link></p></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon><el-button text @click="load">重新加载</el-button></el-alert>
    <div v-else v-loading="loading" class="campus-table-card campus-course-detail">
      <template v-if="course"><span class="campus-course-code">{{ course.code }}</span><h2>{{ course.name }}</h2><el-descriptions :column="1"><el-descriptions-item label="授课教师">{{ course.teacher_name }}</el-descriptions-item><el-descriptions-item label="课程编码">{{ course.code }}</el-descriptions-item></el-descriptions><h3>课程简介</h3><p class="campus-course-full-description">{{ course.description || '暂无课程简介' }}</p><router-link to="/app/schedule" class="campus-card-link">查看我的课表 →</router-link></template>
    </div>
  </section>
</template>
