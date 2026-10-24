<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import type { Course, Lesson, LessonInput } from '../api/courses'
import { listCoursesApi, listLessonsApi, createLessonApi, updateLessonApi, deleteLessonApi } from '../api/courses'
import { errorMessage } from '../utils/campus-request'
import { shanghaiDate } from '../utils/campus-date'

const rows = ref<Lesson[]>([])
const courses = ref<Course[]>([])
const courseId = ref<number>()
const day = ref('')
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const dialogError = ref('')
const editing = ref<Lesson | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ course_id: null as number | null, class_date: shanghaiDate(),
  start_time: '08:00:00', end_time: '09:30:00', period: '', location: '' })
const rules: FormRules = {
  course_id: [{ required: true, message: '请选择课程', trigger: 'change' }],
  class_date: [{ required: true, message: '请选择上课日期', trigger: 'change' }],
  start_time: [{ required: true, message: '请选择开始时间', trigger: 'change' }],
  end_time: [{ required: true, message: '请选择结束时间', trigger: 'change' }, {
    validator: (_rule: unknown, value: string, callback: (error?: Error) => void) =>
      callback(value && value > form.start_time ? undefined : new Error('结束时间必须晚于开始时间')), trigger: 'change' }],
  period: [{ required: true, whitespace: true, message: '请输入节次', trigger: 'blur' }],
  location: [{ required: true, whitespace: true, message: '请输入上课地点', trigger: 'blur' }]
}
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  try {
    const [data, options] = await Promise.all([listLessonsApi({ course_id: courseId.value, date: day.value || undefined }), listCoursesApi('', true)])
    if (id === sequence) { rows.value = data; courses.value = options }
  } catch (cause) { if (id === sequence) { rows.value = []; error.value = errorMessage(cause) } }
  finally { if (id === sequence) loading.value = false }
}
async function openEditor(value?: Lesson) {
  try { courses.value = await listCoursesApi('', true) }
  catch (cause) { ElMessage.error(errorMessage(cause)); return }
  editing.value = value ?? null
  Object.assign(form, value ? { course_id: value.course_id, class_date: value.class_date,
    start_time: value.start_time, end_time: value.end_time, period: value.period, location: value.location } :
    { course_id: courseId.value ?? null, class_date: day.value || shanghaiDate(),
      start_time: '08:00:00', end_time: '09:30:00', period: '', location: '' })
  dialogError.value = ''
  formRef.value?.clearValidate()
  dialog.value = true
}
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false) || !form.course_id) return
  saving.value = true
  dialogError.value = ''
  const data: LessonInput = { ...form, course_id: form.course_id, period: form.period.trim(), location: form.location.trim() }
  try {
    if (editing.value) await updateLessonApi(editing.value.id, data)
    else await createLessonApi(data)
    dialog.value = false
    ElMessage.success('课时已保存')
    await load()
  } catch (cause) { dialogError.value = errorMessage(cause) }
  finally { saving.value = false }
}
async function remove(value: Lesson) {
  try { await ElMessageBox.confirm(`确认删除 ${value.class_date} 的“${value.course_name}”课时？`, '删除课时', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) }
  catch { return }
  try { await deleteLessonApi(value.id); ElMessage.success('课时已删除'); await load() }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}
onMounted(load)
</script>

<template>
  <section>
    <div class="campus-page-heading campus-heading-with-action"><div><p class="campus-eyebrow">ADMINISTRATION</p><h1>排课管理</h1><p>按北京时间维护课时，同一教师或教室不能重复占用。</p></div><el-button type="primary" @click="openEditor()">新增课时</el-button></div>
    <div class="campus-table-card">
      <form class="campus-table-toolbar campus-filter-toolbar" @submit.prevent="load"><el-select v-model="courseId" clearable filterable placeholder="全部课程" aria-label="筛选课程"><el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" /></el-select><el-date-picker v-model="day" type="date" value-format="YYYY-MM-DD" placeholder="全部日期" aria-label="筛选日期" /><el-button native-type="submit" :loading="loading">查询</el-button></form>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="campus-spaced" />
      <el-table v-loading="loading" :data="rows" empty-text="暂无课时安排">
        <el-table-column prop="class_date" label="日期" width="115" /><el-table-column label="时间 / 节次" min-width="145"><template #default="{ row }">{{ row.start_time.slice(0, 5) }}–{{ row.end_time.slice(0, 5) }}<div class="campus-muted campus-small">{{ row.period }} 节</div></template></el-table-column><el-table-column prop="course_name" label="课程" min-width="150" /><el-table-column prop="teacher_name" label="教师" min-width="100" /><el-table-column prop="location" label="地点" min-width="130" /><el-table-column label="操作" width="125"><template #default="{ row }"><el-button link type="primary" @click="openEditor(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="dialog" :title="editing ? '编辑课时' : '新增课时'" width="min(540px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
      <el-alert v-if="dialogError" :title="dialogError" type="error" :closable="false" show-icon class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving">
        <el-form-item label="课程" prop="course_id"><el-select v-model="form.course_id" filterable placeholder="选择已启用课程"><el-option v-for="course in courses" :key="course.id" :label="`${course.name} · ${course.teacher_name}${course.status === 1 ? '' : '（已停用）'}`" :value="course.id" :disabled="course.status !== 1" /></el-select></el-form-item>
        <el-form-item label="上课日期（北京时间）" prop="class_date"><el-date-picker v-model="form.class_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <div class="campus-form-grid"><el-form-item label="开始时间" prop="start_time"><el-time-picker v-model="form.start_time" value-format="HH:mm:ss" format="HH:mm" /></el-form-item><el-form-item label="结束时间" prop="end_time"><el-time-picker v-model="form.end_time" value-format="HH:mm:ss" format="HH:mm" /></el-form-item></div>
        <el-form-item label="节次" prop="period"><el-input v-model="form.period" placeholder="例如：1-2" maxlength="50" /></el-form-item><el-form-item label="上课地点" prop="location"><el-input v-model="form.location" maxlength="100" /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">保存课时</el-button></template>
    </el-dialog>
  </section>
</template>
