<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { todayScheduleApi, weekScheduleApi } from '../api/courses'
import type { Lesson } from '../api/courses'
import { user } from '../utils/campus-auth'
import { errorMessage } from '../utils/campus-request'
import { shanghaiDate, shiftDay, weekday } from '../utils/campus-date'

const mode = ref('week')
const reference = ref(shanghaiDate())
const start = ref('')
const end = ref('')
const lessons = ref<Lesson[]>([])
const loading = ref(false)
const error = ref('')
let sequence = 0
const days = computed(() => start.value ? Array.from({ length: mode.value === 'week' ? 7 : 1 },
  (_, index) => shiftDay(start.value, index)) : [])
async function load() {
  const requestId = ++sequence
  loading.value = true
  error.value = ''
  lessons.value = []
  try {
    if (mode.value === 'week') {
      const data = await weekScheduleApi(reference.value)
      if (requestId !== sequence) return
      start.value = data.start_date
      end.value = data.end_date
      lessons.value = data.list
    } else {
      const data = await todayScheduleApi(reference.value)
      if (requestId !== sequence) return
      start.value = end.value = reference.value
      lessons.value = data
    }
  } catch (cause) { if (requestId === sequence) error.value = errorMessage(cause) }
  finally { if (requestId === sequence) loading.value = false }
}
function resetDate() { reference.value = shanghaiDate(); void load() }
function move(amount: number) { reference.value = shiftDay(reference.value, amount); void load() }
onMounted(load)
</script>

<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">MY TIMETABLE</p><h1>我的课表</h1><p>{{ user?.role === 'teacher' ? '查看本人授课安排' : user?.role === 'admin' ? '管理员可通过排课管理维护全校课时' : '查看本人选课的上课安排' }} · 北京时间</p></div>
    <div class="campus-table-card">
      <div class="campus-schedule-toolbar">
        <el-radio-group v-model="mode" @change="resetDate"><el-radio-button value="week">本周课表</el-radio-button><el-radio-button value="today">今日课表</el-radio-button></el-radio-group>
        <div class="campus-date-controls"><el-button @click="move(mode === 'week' ? -7 : -1)">上一{{ mode === 'week' ? '周' : '天' }}</el-button><el-date-picker v-model="reference" type="date" value-format="YYYY-MM-DD" :clearable="false" aria-label="课表参考日期" @change="load" /><el-button @click="move(mode === 'week' ? 7 : 1)">下一{{ mode === 'week' ? '周' : '天' }}</el-button><el-button text @click="resetDate">回到今天</el-button></div>
      </div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon><el-button text @click="load">重新加载</el-button></el-alert>
      <div v-else v-loading="loading" class="campus-schedule-body">
        <div class="campus-schedule-summary"><h2>{{ start }}<template v-if="mode === 'week'"> — {{ end }}</template></h2><span class="campus-muted">共 {{ lessons.length }} 个课时</span></div>
        <el-empty v-if="!loading && !lessons.length" :description="mode === 'week' ? '本周暂无课程安排' : '当天暂无课程安排'" :image-size="80" />
        <div v-else class="campus-week-grid" :class="{ 'campus-single-day': mode === 'today' }">
          <div v-for="day in days" :key="day" class="campus-day-column">
            <div class="campus-day-heading" :class="{ 'is-today': day === shanghaiDate() }"><strong>{{ weekday(day) }}</strong><span>{{ day.slice(5) }}</span></div>
            <router-link v-for="lesson in lessons.filter(row => row.class_date === day)" :key="lesson.id" :to="`/app/courses/${lesson.course_id}`" class="campus-lesson-card">
              <span class="campus-lesson-time">{{ lesson.start_time.slice(0, 5) }}–{{ lesson.end_time.slice(0, 5) }}</span><h3>{{ lesson.course_name }}</h3><p>{{ lesson.location }}</p><p>{{ lesson.teacher_name }} · {{ lesson.period }} 节</p><span class="campus-lesson-detail">查看课程 →</span>
            </router-link>
            <p v-if="!lessons.some(row => row.class_date === day)" class="campus-day-empty">暂无课程</p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
