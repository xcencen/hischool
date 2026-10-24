<script setup lang="ts">
import { useRoute } from 'vue-router'
import { user, roleLabel } from '../utils/campus-auth'
const route = useRoute()
</script>

<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">MY CAMPUS</p><h1>你好，{{ user?.name }}</h1><p>欢迎回到你的校园，查看课程安排，管理个人信息。</p></div>
    <el-alert v-if="route.query.denied" title="当前账号没有访问管理页面的权限。" type="warning" show-icon :closable="false" class="campus-spaced" />
    <div class="campus-welcome-card">
      <div class="campus-large-avatar">{{ user?.name.slice(0, 1) }}</div>
      <div><el-tag effect="light" round>{{ roleLabel(user?.role) }}</el-tag><h2>{{ user?.name }}</h2><p>账号：{{ user?.username }}</p></div>
      <el-tag type="success" effect="plain" round>账号正常</el-tag>
    </div>
    <div class="campus-card-grid">
      <router-link class="campus-action-card" to="/app/notices"><span class="campus-card-number">通知</span><h2>校园通知</h2><p>查看校园消息与教学安排。</p><span class="campus-card-link">查看通知 →</span></router-link>
      <router-link class="campus-action-card" to="/app/activities"><span class="campus-card-number">活动</span><h2>校园活动</h2><p>了解活动内容，在线报名参加。</p><span class="campus-card-link">浏览活动 →</span></router-link>
      <router-link class="campus-action-card" to="/app/registrations"><span class="campus-card-number">报名</span><h2>我的报名记录</h2><p>管理本人报名，活动开始前可取消。</p><span class="campus-card-link">查看记录 →</span></router-link>
      <router-link class="campus-action-card" to="/app/schedule"><span class="campus-card-number">课表</span><h2>我的课表</h2><p>{{ user?.role === 'teacher' ? '查看本人今日与本周的授课安排。' : '查看本人今日与本周的课程安排。' }}</p><span class="campus-card-link">查看课表 →</span></router-link>
      <router-link class="campus-action-card" to="/app/courses"><span class="campus-card-number">课程</span><h2>校园课程</h2><p>查询课程内容与授课教师。</p><span class="campus-card-link">浏览课程 →</span></router-link>
      <router-link class="campus-action-card" to="/app/profile"><span class="campus-card-number">01</span><h2>个人资料</h2><p>维护姓名、邮箱和联系电话。</p><span class="campus-card-link">编辑资料 →</span></router-link>
      <router-link class="campus-action-card" to="/app/password"><span class="campus-card-number">02</span><h2>账户安全</h2><p>更新登录密码，保护你的账户。</p><span class="campus-card-link">修改密码 →</span></router-link>
      <router-link v-if="user?.role === 'admin'" class="campus-action-card" to="/admin/users"><span class="campus-card-number">03</span><h2>用户管理</h2><p>维护校园用户的角色和使用状态。</p><span class="campus-card-link">进入管理 →</span></router-link>
    </div>
  </section>
</template>
