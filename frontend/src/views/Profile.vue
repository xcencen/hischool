<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { updateProfileApi } from '../api/campus'
import { user, saveUser, roleLabel } from '../utils/campus-auth'
import { errorMessage } from '../utils/campus-request'

const formRef = ref<FormInstance>()
const form = reactive({ name: '', email: '', phone: '' })
const saving = ref(false)
const error = ref('')
const rules: FormRules = {
  name: [{ required: true, whitespace: true, message: '请输入姓名', trigger: 'blur' }, { max: 50, message: '姓名最多50个字符' }],
  email: [{ max: 50, message: '邮箱最多50个字符' }, { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' }],
  phone: [{ max: 50, message: '联系电话最多50个字符' }]
}
onMounted(() => {
  if (user.value) Object.assign(form, { name: user.value.name, email: user.value.email ?? '', phone: user.value.phone ?? '' })
})
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false)) return
  saving.value = true
  error.value = ''
  try {
    const updated = await updateProfileApi({ name: form.name.trim(), email: form.email.trim() || null, phone: form.phone.trim() || null })
    saveUser(updated)
    ElMessage.success('个人资料已保存')
  } catch (cause) { error.value = errorMessage(cause) }
  finally { saving.value = false }
}
</script>

<template>
  <section><div class="campus-page-heading"><p class="campus-eyebrow">PROFILE</p><h1>个人资料</h1><p>维护你的基本信息，让校园联系更方便。</p></div>
    <div class="campus-form-card"><el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <div class="campus-form-grid"><el-form-item label="账号"><el-input :model-value="user?.username" disabled /></el-form-item><el-form-item label="当前身份"><el-input :model-value="roleLabel(user?.role)" disabled /></el-form-item></div>
        <el-form-item label="姓名" prop="name"><el-input v-model="form.name" maxlength="50" autocomplete="name" /></el-form-item>
        <el-form-item label="邮箱" prop="email"><el-input v-model="form.email" maxlength="50" placeholder="选填" autocomplete="email" /></el-form-item>
        <el-form-item label="联系电话" prop="phone"><el-input v-model="form.phone" maxlength="50" placeholder="选填" autocomplete="tel" /></el-form-item>
        <el-button type="primary" native-type="submit" :loading="saving">保存修改</el-button>
      </el-form>
    </div>
  </section>
</template>
