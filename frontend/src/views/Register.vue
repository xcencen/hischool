<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { registerApi } from '../api/campus'
import { errorMessage } from '../utils/campus-request'

const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)
const error = ref('')
const form = reactive({ username: '', name: '', password: '', confirmation: '' })
const rules: FormRules = {
  username: [{ required: true, pattern: /^[A-Za-z0-9_]{3,50}$/, message: '账号需为3至50位字母、数字或下划线', trigger: 'blur' }],
  name: [{ max: 50, message: '姓名最多50个字符', trigger: 'blur' }],
  password: [{ validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
    const length = new TextEncoder().encode(value).length
    callback(length >= 8 && length <= 72 ? undefined : new Error('密码需为8至72个UTF-8字节，建议使用字母、数字和符号'))
  }, trigger: 'blur' }],
  confirmation: [{ validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
    callback(value && value === form.password ? undefined : new Error('两次输入的密码不一致'))
  }, trigger: 'blur' }]
}
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false)) return
  loading.value = true
  error.value = ''
  try {
    await registerApi({ username: form.username.trim(), password: form.password, ...(form.name.trim() ? { name: form.name.trim() } : {}) })
    form.password = ''
    form.confirmation = ''
    await router.replace({ path: '/login', query: { registered: '1' } })
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}
</script>

<template>
  <main class="campus-auth-shell">
    <section class="campus-auth-intro"><router-link class="campus-brand" to="/"><span class="campus-logo">m</span>my-campus</router-link><div><p class="campus-eyebrow">START YOUR JOURNEY</p><h1>加入你的<br />校园空间。</h1><p>建立个人账号，<br />开启便捷的校园服务体验。</p></div><span class="campus-auth-footnote">my-campus · 校园服务平台</span></section>
    <section class="campus-auth-card campus-register-card"><p class="campus-eyebrow">CREATE ACCOUNT</p><h2>注册学生账号</h2><p class="campus-muted">教师及管理员身份由管理员分配。</p>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <el-form-item label="账号" prop="username"><el-input v-model="form.username" placeholder="3至50位字母、数字或下划线" maxlength="50" autocomplete="username" /></el-form-item>
        <el-form-item label="姓名（选填）" prop="name"><el-input v-model="form.name" placeholder="用于校园内展示" maxlength="50" autocomplete="name" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" type="password" show-password placeholder="至少8个字节" autocomplete="new-password" /></el-form-item>
        <el-form-item label="确认密码" prop="confirmation"><el-input v-model="form.confirmation" type="password" show-password placeholder="再次输入密码" autocomplete="new-password" /></el-form-item>
        <el-button class="campus-submit" type="primary" native-type="submit" :loading="loading">创建账号</el-button>
      </el-form>
      <p class="campus-auth-switch">已有账号？<router-link to="/login">返回登录</router-link></p>
    </section>
  </main>
</template>
