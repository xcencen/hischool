<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { categoriesApi, manageListApi, manageDetailApi, saveContentApi, deleteContentApi, reviewContentApi, stateLabel } from '../api/community'
import type { Category, ContentKind, ManagedContent, PublicationInput } from '../api/community'
import { user } from '../utils/campus-auth'
import { errorMessage } from '../utils/campus-request'
import { displayDateTime, shanghaiDateTimeInput, shanghaiInputToUtc } from '../utils/campus-date'

const route = useRoute()
const kind = computed(() => route.meta.contentKind as ContentKind)
const own = computed(() => Boolean(route.meta.ownOnly))
const isNotice = computed(() => kind.value === 'notices')
const label = computed(() => isNotice.value ? '通知' : '活动')
const rows = ref<ManagedContent[]>([])
const categories = ref<Category[]>([])
const q = ref('')
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const editing = ref<number | undefined>()
const saving = ref(false)
const dialogError = ref('')
const formRef = ref<FormInstance>()
const form = reactive({ code: '', title: '', content: '', state: 'pending',
  category_id: null as number | null, location: '', start_time: '', end_time: '',
  registration_deadline: '', capacity: 30 })
const rules: FormRules = {
  code: [{ required: true, whitespace: true, message: '请输入编码', trigger: 'blur' }],
  title: [{ required: true, whitespace: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, whitespace: true, message: '请输入正文', trigger: 'blur' }],
  category_id: [{ required: true, message: '请选择分类', trigger: 'change' }],
  location: [{ required: true, whitespace: true, message: '请输入活动地点', trigger: 'blur' }],
  start_time: [{ required: true, message: '请选择开始时间', trigger: 'change' }],
  end_time: [{ required: true, message: '请选择结束时间', trigger: 'change' }],
  registration_deadline: [{ required: true, message: '请选择报名截止时间', trigger: 'change' }]
}
const reviewDialog = ref(false)
const reviewing = ref<ManagedContent | null>(null)
const reviewNote = ref('')
const reviewError = ref('')
const reviewingLoading = ref(false)
let sequence = 0
let editorSequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  try {
    const data = await manageListApi(kind.value, own.value, { page: page.value, page_size: 10, q: q.value.trim() })
    if (id === sequence) { rows.value = data.list; total.value = data.total }
  } catch (cause) { if (id === sequence) { rows.value = []; error.value = errorMessage(cause) } }
  finally { if (id === sequence) loading.value = false }
}
function search() { page.value = 1; void load() }
async function openEditor(value?: ManagedContent) {
  const id = ++editorSequence
  const selectedKind = kind.value
  try {
    const [current, options] = await Promise.all([
      value ? manageDetailApi(selectedKind, own.value, value.id) : Promise.resolve(null),
      selectedKind === 'notices' ? categoriesApi(user.value?.role === 'admin') : Promise.resolve([])
    ])
    if (id !== editorSequence) return
    categories.value = options
    editing.value = current?.id
    const start = new Date(Date.now() + 7 * 86400000).toISOString()
    Object.assign(form, current ? {
      code: current.code, title: current.title, content: current.content,
      state: user.value?.role === 'teacher' ? 'pending' : current.state === 'rejected' ? 'pending' : current.state,
      category_id: current.category_id ?? null, location: current.location ?? '',
      start_time: current.start_time ? shanghaiDateTimeInput(current.start_time) : '',
      end_time: current.end_time ? shanghaiDateTimeInput(current.end_time) : '',
      registration_deadline: current.registration_deadline ? shanghaiDateTimeInput(current.registration_deadline) : '',
      capacity: current.capacity ?? 30
    } : { code: '', title: '', content: '', state: user.value?.role === 'admin' ? 'published' : 'pending',
      category_id: null, location: '', start_time: shanghaiDateTimeInput(start),
      end_time: shanghaiDateTimeInput(new Date(new Date(start).getTime()+7200000).toISOString()),
      registration_deadline: shanghaiDateTimeInput(new Date(new Date(start).getTime()-86400000).toISOString()), capacity: 30 })
    dialogError.value = ''
    formRef.value?.clearValidate()
    dialog.value = true
  } catch (cause) { ElMessage.error(errorMessage(cause)) }
}
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false)) return
  saving.value = true
  dialogError.value = ''
  try {
    const data: PublicationInput = { title: form.title.trim(), content: form.content.trim(), state: form.state }
    if (!editing.value) data.code = form.code.trim()
    if (isNotice.value) data.category_id = form.category_id ?? undefined
    else {
      Object.assign(data, { location: form.location.trim(), capacity: form.capacity,
        start_time: shanghaiInputToUtc(form.start_time), end_time: shanghaiInputToUtc(form.end_time),
        registration_deadline: shanghaiInputToUtc(form.registration_deadline) })
      if (data.end_time! <= data.start_time! || data.registration_deadline! > data.start_time!) {
        dialogError.value = '报名截止不得晚于开始时间，结束时间须晚于开始时间'
        return
      }
    }
    await saveContentApi(kind.value, own.value, data, editing.value)
    dialog.value = false
    ElMessage.success(user.value?.role === 'teacher' && form.state === 'pending' ? '已提交，等待管理员审核' : '内容已保存')
    await load()
  } catch (cause) { dialogError.value = errorMessage(cause) }
  finally { saving.value = false }
}
async function remove(row: ManagedContent) {
  try { await ElMessageBox.confirm(`确认删除“${row.title}”？活动存在报名记录时将保留并拒绝删除。`, '删除内容', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) }
  catch { return }
  try { await deleteContentApi(kind.value, own.value, row.id); ElMessage.success('已删除'); await load() }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}
async function openReview(row: ManagedContent) {
  const id = ++editorSequence
  reviewDialog.value = true
  reviewing.value = null
  reviewError.value = ''
  reviewNote.value = ''
  reviewingLoading.value = true
  try { const value = await manageDetailApi(kind.value, false, row.id); if (id === editorSequence) reviewing.value = value }
  catch (cause) { if (id === editorSequence) reviewError.value = errorMessage(cause) }
  finally { if (id === editorSequence) reviewingLoading.value = false }
}
async function review(action: 'publish' | 'reject') {
  if (!reviewing.value) return
  if (action === 'reject' && !reviewNote.value.trim()) { reviewError.value = '退回时请填写原因'; return }
  saving.value = true
  reviewError.value = ''
  try {
    await reviewContentApi(kind.value, reviewing.value.id, { action, expected_revision: reviewing.value.revision, note: reviewNote.value.trim() })
    reviewDialog.value = false
    ElMessage.success(action === 'publish' ? '审核通过，内容已发布' : '内容已退回')
    await load()
  } catch (cause) { reviewError.value = errorMessage(cause) }
  finally { saving.value = false }
}
watch(() => route.fullPath, () => {
  ++editorSequence
  dialog.value = reviewDialog.value = false
  rows.value = []
  q.value = ''
  page.value = 1
  void load()
}, { immediate: true })
</script>
<template>
  <section>
    <div class="campus-page-heading campus-heading-with-action"><div><p class="campus-eyebrow">{{ own ? 'MY PUBLICATIONS' : 'ADMINISTRATION' }}</p><h1>{{ own ? '我发布的' : '' }}{{ label }}{{ own ? '' : '管理' }}</h1><p>{{ own ? '维护本人内容；教师提交后由管理员审核，修改已发布内容需重新审核。' : '维护校园内容，审核教师提交并发布。' }}</p></div><el-button type="primary" @click="openEditor()">新增{{ label }}</el-button></div>
    <div class="campus-table-card">
      <form class="campus-table-toolbar" @submit.prevent="search"><el-input v-model="q" placeholder="搜索标题或正文" maxlength="100" clearable aria-label="搜索管理内容" /><el-button native-type="submit" :loading="loading">搜索</el-button></form>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="campus-spaced" />
      <el-table v-loading="loading" :data="rows" empty-text="暂无内容"><el-table-column prop="title" label="标题" min-width="200" /><el-table-column prop="publisher_name" label="发布人" min-width="100" /><el-table-column v-if="isNotice" prop="category_name" label="分类" min-width="100" /><el-table-column v-else label="报名人数" width="100"><template #default="{ row }">{{ row.enrolled_count }} / {{ row.capacity }}</template></el-table-column><el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.state === 'published' ? 'success' : row.state === 'pending' ? 'warning' : 'info'" effect="plain">{{ stateLabel(row.state) }}</el-tag></template></el-table-column><el-table-column label="审核意见" min-width="140"><template #default="{ row }">{{ row.review_note || '—' }}</template></el-table-column><el-table-column label="操作" width="190"><template #default="{ row }"><el-button link type="primary" @click="openEditor(row)">编辑</el-button><el-button v-if="!own && row.state === 'pending'" link type="primary" @click="openReview(row)">审核</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column></el-table>
      <el-pagination v-if="total > 10" v-model:current-page="page" :total="total" :page-size="10" layout="prev, pager, next" class="campus-pagination" @current-change="load" />
    </div>
    <el-dialog v-model="dialog" :title="(editing ? '编辑' : '新增') + label" width="min(680px, 95vw)" class="campus-content-dialog" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
      <el-alert v-if="dialogError" :title="dialogError" type="error" :closable="false" show-icon class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving">
        <div class="campus-form-grid"><el-form-item label="编码" prop="code"><el-input v-model="form.code" maxlength="50" :disabled="!!editing" /></el-form-item><el-form-item label="保存状态"><el-select v-model="form.state"><el-option label="草稿" value="draft" /><el-option label="提交审核" value="pending" /><el-option v-if="user?.role === 'admin'" label="直接发布" value="published" /></el-select></el-form-item></div>
        <el-form-item label="标题" prop="title"><el-input v-model="form.title" maxlength="150" /></el-form-item>
        <el-form-item v-if="isNotice" label="通知分类" prop="category_id"><el-select v-model="form.category_id" placeholder="选择分类"><el-option v-for="category in categories" :key="category.id" :value="category.id" :label="category.name + (category.status ? '' : '（已停用）')" :disabled="category.status !== 1" /></el-select></el-form-item>
        <template v-else><el-form-item label="活动地点" prop="location"><el-input v-model="form.location" maxlength="100" /></el-form-item><div class="campus-form-grid"><el-form-item label="开始时间（北京时间）" prop="start_time"><el-date-picker v-model="form.start_time" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" /></el-form-item><el-form-item label="结束时间（北京时间）" prop="end_time"><el-date-picker v-model="form.end_time" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" /></el-form-item></div><div class="campus-form-grid"><el-form-item label="报名截止（北京时间）" prop="registration_deadline"><el-date-picker v-model="form.registration_deadline" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" /></el-form-item><el-form-item label="活动容量"><el-input-number v-model="form.capacity" :min="1" :max="100000" :precision="0" /></el-form-item></div></template>
        <el-form-item label="正文" prop="content"><el-input v-model="form.content" type="textarea" :rows="6" maxlength="20000" show-word-limit /></el-form-item>
      </el-form><template #footer><el-button :disabled="saving" @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">保存{{ label }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="reviewDialog" title="审核内容" width="min(680px, 95vw)" class="campus-content-dialog" :close-on-click-modal="false" :show-close="!saving">
      <el-alert v-if="reviewError" :title="reviewError" type="error" :closable="false" show-icon class="campus-spaced" />
      <div v-loading="reviewingLoading"><template v-if="reviewing"><el-tag>{{ stateLabel(reviewing.state) }} · 第 {{ reviewing.revision }} 版</el-tag><h2 class="campus-review-title">{{ reviewing.title }}</h2><p class="campus-muted">{{ reviewing.publisher_name }}<template v-if="reviewing.start_time"> · {{ displayDateTime(reviewing.start_time) }} · {{ reviewing.location }} · 容量 {{ reviewing.capacity }}</template><template v-else> · {{ reviewing.category_name }}</template></p><div class="campus-review-content">{{ reviewing.content }}</div><el-input v-model="reviewNote" type="textarea" :rows="2" maxlength="500" placeholder="审核意见，退回时必填" aria-label="审核意见" :disabled="saving" /></template></div>
      <template #footer><el-button v-if="reviewing" :disabled="saving" @click="openReview(reviewing)">刷新内容</el-button><el-button :disabled="saving || !reviewing || reviewing.state !== 'pending'" @click="review('reject')">退回</el-button><el-button type="primary" :loading="saving" :disabled="!reviewing || reviewing.state !== 'pending'" @click="review('publish')">通过并发布</el-button></template>
    </el-dialog>
  </section>
</template>
