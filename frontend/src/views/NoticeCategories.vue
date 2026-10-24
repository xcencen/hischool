<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { categoriesApi, saveCategoryApi, deleteCategoryApi } from '../api/community'
import type { Category } from '../api/community'
import { errorMessage } from '../utils/campus-request'
const rows = ref<Category[]>([])
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const editing = ref<number>()
const dialogError = ref('')
const formRef = ref<FormInstance>()
const form = reactive({ code: '', name: '', status: 1 })
const rules: FormRules = { code: [{ required: true, whitespace: true, message: '请输入分类编码', trigger: 'blur' }],
  name: [{ required: true, whitespace: true, message: '请输入分类名称', trigger: 'blur' }] }
async function load() {
  loading.value = true
  error.value = ''
  try { rows.value = await categoriesApi(true) }
  catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}
function open(value?: Category) {
  editing.value = value?.id
  Object.assign(form, value ?? { code: '', name: '', status: 1 })
  dialogError.value = ''
  formRef.value?.clearValidate()
  dialog.value = true
}
async function save() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false)) return
  saving.value = true
  dialogError.value = ''
  try {
    await saveCategoryApi({ name: form.name.trim(), status: form.status, ...(!editing.value ? { code: form.code.trim() } : {}) }, editing.value)
    dialog.value = false
    ElMessage.success('分类已保存')
    await load()
  } catch (cause) { dialogError.value = errorMessage(cause) }
  finally { saving.value = false }
}
async function remove(row: Category) {
  try { await ElMessageBox.confirm(`确认删除分类“${row.name}”？有关联通知时请改为停用。`, '删除分类', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }) }
  catch { return }
  try { await deleteCategoryApi(row.id); ElMessage.success('分类已删除'); await load() }
  catch (cause) { ElMessage.error(errorMessage(cause)) }
}
onMounted(load)
</script>
<template>
  <section>
    <div class="campus-page-heading campus-heading-with-action"><div><p class="campus-eyebrow">ADMINISTRATION</p><h1>通知分类</h1><p>维护通知分类；停用后关联通知不在校园端展示。</p></div><el-button type="primary" @click="open()">新增分类</el-button></div>
    <div class="campus-table-card"><el-alert v-if="error" :title="error" type="error" :closable="false" class="campus-spaced" show-icon /><el-table v-loading="loading" :data="rows" empty-text="暂无分类"><el-table-column prop="code" label="编码" min-width="140" /><el-table-column prop="name" label="名称" min-width="150" /><el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.status === 1 ? 'success' : 'info'" effect="plain">{{ row.status === 1 ? '启用' : '停用' }}</el-tag></template></el-table-column><el-table-column label="操作" width="150"><template #default="{ row }"><el-button link type="primary" @click="open(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column></el-table></div>
    <el-dialog v-model="dialog" :title="editing ? '编辑分类' : '新增分类'" width="min(480px, 94vw)" :close-on-click-modal="false" :show-close="!saving"><el-alert v-if="dialogError" :title="dialogError" type="error" :closable="false" class="campus-spaced" show-icon /><el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving"><el-form-item label="分类编码" prop="code"><el-input v-model="form.code" maxlength="50" :disabled="!!editing" /></el-form-item><el-form-item label="分类名称" prop="name"><el-input v-model="form.name" maxlength="50" /></el-form-item><el-form-item label="状态"><el-radio-group v-model="form.status"><el-radio :value="1">启用</el-radio><el-radio :value="0">停用</el-radio></el-radio-group></el-form-item></el-form><template #footer><el-button :disabled="saving" @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存分类</el-button></template></el-dialog>
  </section>
</template>
