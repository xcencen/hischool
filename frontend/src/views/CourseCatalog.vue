<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Course } from '../api/courses'
import { listCoursesApi } from '../api/courses'
import { errorMessage } from '../utils/campus-request'

const courses = ref<Course[]>([])
const q = ref('')
const loading = ref(false)
const error = ref('')
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  try { const data = await listCoursesApi(q.value.trim()); if (id === sequence) courses.value = data }
  catch (cause) { if (id === sequence) { courses.value = []; error.value = errorMessage(cause) } }
  finally { if (id === sequence) loading.value = false }
}
onMounted(load)
</script>

<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">COURSE CATALOG</p><h1>校园课程</h1><p>了解课程内容与授课教师，个人上课安排请查看我的课表。</p></div>
    <form class="campus-table-toolbar" @submit.prevent="load"><el-input v-model="q" placeholder="搜索课程名称或编码" maxlength="100" clearable aria-label="搜索课程" /><el-button type="primary" native-type="submit" :loading="loading">搜索</el-button></form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="campus-spaced" />
    <div v-loading="loading" class="campus-course-list">
      <router-link v-for="course in courses" :key="course.id" :to="`/app/courses/${course.id}`" class="campus-course-card"><div class="campus-course-code">{{ course.code }}</div><h2>{{ course.name }}</h2><p class="campus-muted">授课教师 · {{ course.teacher_name }}</p><p class="campus-course-description">{{ course.description || '暂无课程简介' }}</p><span class="campus-card-link">查看课程详情 →</span></router-link>
    </div>
    <el-empty v-if="!loading && !error && !courses.length" description="暂无符合条件的课程" />
  </section>
</template>
