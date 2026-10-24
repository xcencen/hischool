<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { updatePasswordApi } from '../api/campus'
import { clearSession } from '../utils/campus-auth'
import { errorMessage } from '../utils/campus-request'

const router = useRouter()
const formRef = ref<FormInstance>()
const form = reactive({ old_password: '', new_password: '', confirmation: '' })
const saving = ref(false)
const error = ref('')
const rules: FormRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [{ validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
    const length = new TextEncoder().encode(value).length
    callback(length < 8 || length > 72 ? new Error('新密码需为8至72个UTF-8字节') : value === form.old_password ? new Error('新密码不能与当前密码相同') : undefined)
  }, trigger: 'blur' }],
  confirmation: [{ validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
    callback(value && value === form.new_password ? undefined : new Error('两次输入的新密码不一致'))
  }, trigger: 'blur' }]
}
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false)) return
  saving.value = true
  error.value = ''
  try {
    await updatePasswordApi({ old_password: form.old_password, new_password: form.new_password })
    Object.assign(form, { old_password: '', new_password: '', confirmation: '' })
    clearSession()
    await router.replace({ path: '/login', query: { passwordChanged: '1' } })
  } catch (cause) { error.value = errorMessage(cause) }
  finally { saving.value = false }
}
</script>

<template>
  <section><div class="campus-page-heading"><p class="campus-eyebrow">ACCOUNT SECURITY</p><h1>账户安全</h1><p>定期更新密码，保护你的校园账号。</p></div>
    <div class="campus-form-card"><el-alert title="密码修改成功后，原有登录凭证将失效，需要重新登录。" type="info" show-icon :closable="false" class="campus-spaced" /><el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <el-form-item label="当前密码" prop="old_password"><el-input v-model="form.old_password" type="password" show-password autocomplete="current-password" /></el-form-item>
        <el-form-item label="新密码" prop="new_password"><el-input v-model="form.new_password" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="确认新密码" prop="confirmation"><el-input v-model="form.confirmation" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-button type="primary" native-type="submit" :loading="saving">更新密码</el-button>
      </el-form>
    </div>
  </section>
</template>
