<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { login, safeRedirect } from '../utils/campus-auth'
import { errorMessage } from '../utils/campus-request'

const route = useRoute()
const router = useRouter()
const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })
const loading = ref(false)
const error = ref('')
const notice = ref('')
const rules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}
onMounted(() => {
  if (route.query.registered) notice.value = '注册成功，请使用新账号登录。'
  if (route.query.passwordChanged) notice.value = '密码已更新，请重新登录。'
  if (route.query.expired) error.value = '登录状态已失效，请重新登录。'
})
async function submit() {
  if (!formRef.value || !await formRef.value.validate().catch(() => false)) return
  loading.value = true
  error.value = ''
  try {
    await login({ username: form.username.trim(), password: form.password })
    form.password = ''
    await router.replace(safeRedirect(route.query.redirect))
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}
</script>

<template>
  <main class="campus-auth-shell">
    <section class="campus-auth-intro">
      <router-link class="campus-brand" to="/"><span class="campus-logo">m</span>my-campus</router-link>
      <div><p class="campus-eyebrow">YOUR CAMPUS, CONNECTED</p><h1>校园生活，<br />从这里开始。</h1><p>一个属于你的校园空间，<br />让信息与服务触手可及。</p></div>
      <span class="campus-auth-footnote">my-campus · 校园服务平台</span>
    </section>
    <section class="campus-auth-card">
      <p class="campus-eyebrow">WELCOME BACK</p><h2>欢迎回来</h2><p class="campus-muted">登录你的校园账号</p>
      <el-alert v-if="notice" :title="notice" type="success" show-icon :closable="false" class="campus-spaced" />
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="campus-spaced" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large" @submit.prevent="submit">
        <el-form-item label="账号" prop="username"><el-input v-model="form.username" placeholder="请输入账号" maxlength="50" autocomplete="username" /></el-form-item>
        <el-form-item label="密码" prop="password"><el-input v-model="form.password" type="password" placeholder="请输入密码" show-password autocomplete="current-password" /></el-form-item>
        <el-button class="campus-submit" type="primary" native-type="submit" :loading="loading">登录</el-button>
      </el-form>
      <p class="campus-auth-switch">还没有账号？<router-link to="/register">注册学生账号</router-link></p>
      <router-link class="campus-inline-link" to="/status">查看服务连接状态 ↗</router-link>
    </section>
  </main>
</template>
