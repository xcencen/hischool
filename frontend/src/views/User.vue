<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import type { CampusUser, Role, CreateUserData, AdminUserData } from '../api/campus'
import { listUsersApi, createUserApi, updateUserApi } from '../api/campus'
import { user, saveUser, clearSession, roleLabel } from '../utils/campus-auth'
import { errorMessage } from '../utils/campus-request'

const router = useRouter()
const users = ref<CampusUser[]>([])
const total = ref(0)
const q = ref('')
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const dialogError = ref('')
const editing = ref<CampusUser | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '', name: '', email: '', phone: '', role: 'student' as Role, status: 1 })
let sequence = 0
const rules: FormRules = {
  username: [{ required: true, pattern: /^[A-Za-z0-9_]{3,50}$/, message: '账号需为3至50位字母、数字或下划线', trigger: 'blur' }],
  name: [{ required: true, whitespace: true, message: '请输入姓名', trigger: 'blur' }, { max: 50, message: '姓名最多50个字符' }],
  email: [{ max: 50, message: '邮箱最多50个字符' }, { type: 'email', message: '请输入有效的邮箱', trigger: 'blur' }],
  phone: [{ max: 50, message: '联系电话最多50个字符' }],
  password: [{ validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
    if (editing.value) return callback()
    const length = new TextEncoder().encode(value).length
    callback(length >= 8 && length <= 72 ? undefined : new Error('密码需为8至72个UTF-8字节'))
  }, trigger: 'blur' }]
}
async function load() {
  const requestId = ++sequence
  loading.value = true
  error.value = ''
  try {
    const result = await listUsersApi({ q: q.value.trim(), page: page.value, page_size: pageSize.value })
    if (requestId !== sequence) return
    users.value = result.list
    total.value = result.total
  } catch (cause) { if (requestId === sequence) error.value = errorMessage(cause) }
  finally { if (requestId === sequence) loading.value = false }
}
function search() { page.value = 1; void load() }
function openEditor(value?: CampusUser) {
  editing.value = value ? { ...value } : null
  Object.assign(form, value ? {
    username: value.username, password: '', name: value.name, email: value.email ?? '',
    phone: value.phone ?? '', role: value.role, status: value.status
  } : { username: '', password: '', name: '', email: '', phone: '', role: 'student', status: 1 })
  dialogError.value = ''
  dialog.value = true
}
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false)) return
  saving.value = true
  dialogError.value = ''
  const original = editing.value
  const data: AdminUserData = {
    name: form.name.trim(), email: form.email.trim() || null, phone: form.phone.trim() || null,
    role: form.role, status: form.status
  }
  try {
    const updated = original
      ? await updateUserApi(original.id, data)
      : await createUserApi({ ...data, username: form.username.trim(), password: form.password } satisfies CreateUserData)
    form.password = ''
    dialog.value = false
    ElMessage.success(original ? '用户信息已更新' : '用户已创建')
    if (original && original.id === user.value?.id) {
      if (original.role !== updated.role || original.status !== updated.status) {
        clearSession()
        await router.replace('/login')
        return
      }
      saveUser(updated)
    }
    await load()
  } catch (cause) { dialogError.value = errorMessage(cause) }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section>
    <div class="campus-page-heading campus-heading-with-action"><div><p class="campus-eyebrow">ADMINISTRATION</p><h1>用户管理</h1><p>管理校园账号、角色与使用状态。</p></div><el-button type="primary" @click="openEditor()">创建用户</el-button></div>
    <div class="campus-table-card">
      <form class="campus-table-toolbar" @submit.prevent="search"><el-input v-model="q" placeholder="搜索账号或姓名" maxlength="50" clearable aria-label="搜索用户" /><el-button native-type="submit" :loading="loading">搜索</el-button></form>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="campus-spaced" />
      <el-table v-loading="loading" :data="users" row-key="id" empty-text="暂无符合条件的用户">
        <el-table-column prop="username" label="账号" min-width="140" />
        <el-table-column prop="name" label="姓名" min-width="120" />
        <el-table-column label="角色" width="110"><template #default="{ row }"><el-tag :type="row.role === 'admin' ? 'danger' : row.role === 'teacher' ? 'warning' : 'info'" effect="light" round>{{ roleLabel(row.role) }}</el-tag></template></el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.email || '—' }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 1 ? 'success' : 'info'" effect="plain">{{ row.status === 1 ? '正常' : '已禁用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button type="primary" link @click="openEditor(row)">编辑</el-button></template></el-table-column>
      </el-table>
      <div class="campus-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10, 20, 50]" layout="total, prev, pager, next, sizes" @current-change="load" @size-change="search" /></div>
    </div>
    <el-dialog v-model="dialog" :title="editing ? '编辑用户' : '创建用户'" width="min(540px, 92vw)" :close-on-click-modal="false" @opened="formRef?.clearValidate()">
      <el-alert v-if="dialogError" :title="dialogError" type="error" show-icon :closable="false" class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <div class="campus-form-grid"><el-form-item label="账号" prop="username"><el-input v-model="form.username" :disabled="!!editing" maxlength="50" autocomplete="off" /></el-form-item><el-form-item label="姓名" prop="name"><el-input v-model="form.name" maxlength="50" /></el-form-item></div>
        <el-form-item v-if="!editing" label="初始密码" prop="password"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /></el-form-item>
        <div class="campus-form-grid"><el-form-item label="角色" prop="role"><el-select v-model="form.role"><el-option label="学生" value="student" /><el-option label="教师" value="teacher" /><el-option label="管理员" value="admin" /></el-select></el-form-item><el-form-item label="状态" prop="status"><el-select v-model="form.status"><el-option label="正常" :value="1" /><el-option label="禁用" :value="0" /></el-select></el-form-item></div>
        <el-form-item label="邮箱" prop="email"><el-input v-model="form.email" maxlength="50" /></el-form-item><el-form-item label="联系电话" prop="phone"><el-input v-model="form.phone" maxlength="50" /></el-form-item>
        <p v-if="editing" class="campus-muted campus-small">角色或状态调整后，该用户需要重新登录。最后一名有效管理员不能被禁用或降级。</p>
      </el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">{{ editing ? '保存修改' : '创建用户' }}</el-button></template>
    </el-dialog>
  </section>
</template>
