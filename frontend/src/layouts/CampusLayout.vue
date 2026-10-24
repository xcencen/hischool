<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { House, User, Lock, Setting, SwitchButton, Calendar, Reading, Collection, Clock } from '@element-plus/icons-vue'
import { user, roleLabel, logout } from '../utils/campus-auth'
import { errorMessage } from '../utils/campus-request'

const router = useRouter()
const route = useRoute()
const leaving = ref(false)
async function signOut() {
  leaving.value = true
  try { await logout() }
  catch (error) { ElMessage.error(errorMessage(error)) }
  finally { leaving.value = false; await router.replace('/login') }
}
</script>

<template>
  <div class="campus-layout">
    <header class="campus-header">
      <router-link class="campus-brand" to="/app"><span class="campus-logo">m</span>my-campus<span class="campus-brand-caption">校园服务</span></router-link>
      <div class="campus-account"><span class="campus-avatar">{{ user?.name.slice(0, 1) }}</span><span class="campus-account-name">{{ user?.name }}<small>{{ roleLabel(user?.role) }}</small></span><el-button text :icon="SwitchButton" :loading="leaving" @click="signOut">退出</el-button></div>
    </header>
    <aside class="campus-sidebar">
      <p class="campus-nav-label">我的校园</p>
      <nav aria-label="校园导航">
        <router-link to="/app" :class="{ active: route.path === '/app' }"><el-icon><House /></el-icon>校园首页</router-link>
        <router-link to="/app/schedule" active-class="active"><el-icon><Calendar /></el-icon>我的课表</router-link>
        <router-link to="/app/courses" active-class="active"><el-icon><Reading /></el-icon>校园课程</router-link>
        <router-link to="/app/profile" active-class="active"><el-icon><User /></el-icon>个人资料</router-link>
        <router-link to="/app/password" active-class="active"><el-icon><Lock /></el-icon>账户安全</router-link>
        <router-link v-if="user?.role === 'admin'" to="/admin/users" active-class="active"><el-icon><Setting /></el-icon>用户管理</router-link>
        <router-link v-if="user?.role === 'admin'" to="/admin/courses" active-class="active"><el-icon><Collection /></el-icon>课程管理</router-link>
        <router-link v-if="user?.role === 'admin'" to="/admin/schedules" active-class="active"><el-icon><Clock /></el-icon>排课管理</router-link>
      </nav>
      <router-link class="campus-status-link" to="/status">查看服务连接状态 ↗</router-link>
    </aside>
    <main class="campus-content"><router-view /></main>
  </div>
</template>
