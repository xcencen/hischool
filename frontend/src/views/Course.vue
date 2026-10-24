<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import type { Course, PersonOption } from '../api/courses'
import { listCoursesApi, courseOptionsApi, createCourseApi, updateCourseApi,
  deleteCourseApi, courseStudentsApi, saveCourseStudentsApi } from '../api/courses'
import { errorMessage } from '../utils/campus-request'

const rows = ref<Course[]>([])
const teachers = ref<PersonOption[]>([])
const students = ref<PersonOption[]>([])
const q = ref('')
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const editing = ref<Course | null>(null)
const saving = ref(false)
const dialogError = ref('')
const formRef = ref<FormInstance>()
const form = reactive({ code: '', name: '', teacher_id: null as number | null, description: '', status: 1 })
const rules: FormRules = {
  code: [{ required: true, whitespace: true, message: '请输入课程编码', trigger: 'blur' }, { max: 50, message: '最多50个字符' }],
  name: [{ required: true, whitespace: true, message: '请输入课程名称', trigger: 'blur' }, { max: 100, message: '最多100个字符' }],
  teacher_id: [{ required: true, message: '请选择授课教师', trigger: 'change' }]
}
const enrollmentDialog = ref(false)
const enrollmentCourse = ref<Course | null>(null)
const studentIds = ref<number[]>([])
const enrollmentLoading = ref(false)
const enrollmentError = ref('')
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  try { const data = await listCoursesApi(q.value.trim(), true); if (id === sequence) rows.value = data }
  catch (cause) { if (id === sequence) { rows.value = []; error.value = errorMessage(cause) } }
  finally { if (id === sequence) loading.value = false }
}
async function openEditor(value?: Course) {
  dialogError.value = ''
  try {
    const options = await courseOptionsApi()
    teachers.value = options.teachers
    if (value && !teachers.value.some(row => row.id === value.teacher_id)) {
      teachers.value.push({ id: value.teacher_id, name: value.teacher_name + '（不可用，请重新选择）', username: '' })
    }
    editing.value = value ?? null
    Object.assign(form, value ? { ...value, description: value.description ?? '' } :
      { code: '', name: '', teacher_id: null, description: '', status: 1 })
    formRef.value?.clearValidate()
    dialog.value = true
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false) || !form.teacher_id) return
  saving.value = true
  dialogError.value = ''
  const data = { code: form.code.trim(), name: form.name.trim(), teacher_id: form.teacher_id,
    description: form.description.trim() || null, status: form.status }
  try {
    if (editing.value) await updateCourseApi(editing.value.id, data)
    else await createCourseApi(data)
    dialog.value = false
    ElMessage.success('课程已保存')
    await load()
  } catch (cause) { dialogError.value = errorMessage(cause) }
  finally { saving.value = false }
}
async function remove(value: Course) {
  try { await ElMessageBox.confirm(`确认删除“${value.name}”？已有课时的课程需先移除课时。`, '删除课程', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) }
  catch { return }
  try { await deleteCourseApi(value.id); ElMessage.success('课程已删除'); await load() }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}
async function openStudents(value: Course) {
  enrollmentCourse.value = value
  enrollmentDialog.value = true
  enrollmentLoading.value = true
  enrollmentError.value = ''
  students.value = []
  studentIds.value = []
  try {
    const [options, selected] = await Promise.all([courseOptionsApi(), courseStudentsApi(value.id)])
    students.value = options.students
    selected.forEach(row => {
      if (!students.value.some(option => option.id === row.id)) students.value.push({ ...row, name: row.name + '（不可用，请移除）' })
    })
    studentIds.value = selected.map(row => row.id)
  } catch (cause) { enrollmentError.value = errorMessage(cause) }
  finally { enrollmentLoading.value = false }
}
async function saveStudents() {
  if (!enrollmentCourse.value) return
  saving.value = true
  enrollmentError.value = ''
  try {
    await saveCourseStudentsApi(enrollmentCourse.value.id, studentIds.value)
    enrollmentDialog.value = false
    ElMessage.success('选课名单已保存')
  } catch (cause) { enrollmentError.value = errorMessage(cause) }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section>
    <div class="campus-page-heading campus-heading-with-action"><div><p class="campus-eyebrow">ADMINISTRATION</p><h1>课程管理</h1><p>维护课程、授课教师和选课学生。</p></div><el-button type="primary" @click="openEditor()">新增课程</el-button></div>
    <div class="campus-table-card">
      <form class="campus-table-toolbar" @submit.prevent="load"><el-input v-model="q" placeholder="搜索课程名称或编码" maxlength="100" clearable aria-label="搜索管理课程" /><el-button native-type="submit" :loading="loading">搜索</el-button></form>
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="campus-spaced" show-icon />
      <el-table v-loading="loading" :data="rows" empty-text="暂无课程">
        <el-table-column prop="code" label="课程编码" min-width="135" /><el-table-column prop="name" label="课程名称" min-width="150" /><el-table-column prop="teacher_name" label="授课教师" min-width="110" /><el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status === 1 ? 'success' : 'info'" effect="plain">{{ row.status === 1 ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="240"><template #default="{ row }"><el-button link type="primary" @click="openEditor(row)">编辑</el-button><el-button link type="primary" @click="openStudents(row)">选课学生</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="dialog" :title="editing ? '编辑课程' : '新增课程'" width="min(540px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
      <el-alert v-if="dialogError" :title="dialogError" type="error" :closable="false" show-icon class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving">
        <el-form-item label="课程编码" prop="code"><el-input v-model="form.code" maxlength="50" /></el-form-item>
        <el-form-item label="课程名称" prop="name"><el-input v-model="form.name" maxlength="100" /></el-form-item>
        <el-form-item label="授课教师" prop="teacher_id"><el-select v-model="form.teacher_id" placeholder="选择教师" filterable><el-option v-for="teacher in teachers" :key="teacher.id" :label="`${teacher.name} · ${teacher.username}`" :value="teacher.id" /></el-select></el-form-item>
        <el-form-item label="课程简介"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="10000" /></el-form-item>
        <el-form-item label="状态"><el-radio-group v-model="form.status"><el-radio :value="1">启用</el-radio><el-radio :value="0">停用</el-radio></el-radio-group></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">保存课程</el-button></template>
    </el-dialog>
    <el-dialog v-model="enrollmentDialog" title="维护选课学生" width="min(560px, 94vw)" :close-on-click-modal="false" :show-close="!saving">
      <p class="campus-muted">{{ enrollmentCourse?.name }} · 选择后保存完整选课名单。</p>
      <el-alert v-if="enrollmentError" :title="enrollmentError" type="error" :closable="false" show-icon class="campus-spaced" />
      <div v-loading="enrollmentLoading"><el-select v-model="studentIds" multiple filterable placeholder="搜索并选择学生" aria-label="选课学生" :disabled="saving || enrollmentLoading"><el-option v-for="student in students" :key="student.id" :label="`${student.name} · ${student.username}`" :value="student.id" /></el-select></div>
      <template #footer><el-button :disabled="saving" @click="enrollmentDialog = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="enrollmentLoading || (!!enrollmentError && !students.length)" @click="saveStudents">保存名单</el-button></template>
    </el-dialog>
  </section>
</template>
