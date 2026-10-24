<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { safeRedirect, clearSession } from '../utils/campus-auth'
const route = useRoute()
const router = useRouter()
const checking = ref(false)
async function retry() {
  checking.value = true
  try { await router.replace(safeRedirect(route.query.redirect)) }
  finally { checking.value = false }
}
function signInAgain() { clearSession(); void router.replace('/login') }
</script>

<template>
  <main class="campus-auth-shell"><section class="campus-auth-card campus-recovery-card"><p class="campus-eyebrow">MY CAMPUS</p><h1>暂时无法验证登录状态</h1><p class="campus-muted">{{ typeof route.query.message === 'string' ? route.query.message : '服务暂不可用，请稍后重试。' }}</p><p class="campus-muted">登录凭证已保留，你可以恢复连接后继续访问。</p><el-button type="primary" :loading="checking" @click="retry">重新连接</el-button><el-button @click="signInAgain">返回登录</el-button><router-link class="campus-inline-link" to="/status">查看服务状态</router-link></section></main>
</template>
