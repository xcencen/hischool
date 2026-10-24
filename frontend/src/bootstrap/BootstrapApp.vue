<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, Check, Connection, RefreshRight, Warning } from '@element-plus/icons-vue'
import { checkBackendHealth, healthEndpoint } from './health'
import type { HealthData, HealthResult } from './health'

type ConnectionState = 'checking' | HealthResult['state']

const state = ref<ConnectionState>('checking')
const message = ref('正在检查后端服务，请稍候。')
const health = ref<HealthData | null>(null)
const checkedAt = ref('')
let request: AbortController | null = null

const labels: Record<ConnectionState, string> = {
  checking: '检查中',
  online: '连接正常',
  offline: '未连接',
  incompatible: '响应不兼容'
}
const statusLabel = computed(() => labels[state.value])
const statusType = computed(() => {
  if (state.value === 'online') return 'success'
  if (state.value === 'offline' || state.value === 'incompatible') return 'warning'
  return 'info'
})

async function refreshHealth() {
  request?.abort()
  const currentRequest = new AbortController()
  request = currentRequest
  state.value = 'checking'
  message.value = '正在检查后端服务，请稍候。'
  health.value = null
  const result = await checkBackendHealth(currentRequest.signal)
  if (currentRequest.signal.aborted) return

  state.value = result.state
  message.value = result.message
  health.value = result.state === 'online' ? result.data : null
  checkedAt.value = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(new Date())
}

onMounted(refreshHealth)
onBeforeUnmount(() => request?.abort())
</script>

<template>
  <div class="bootstrap-shell">
    <header class="site-header">
      <a class="brand" href="/" aria-label="my-campus 首页">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none">
            <path d="m5 12 11-6 11 6-11 6-11-6Z" stroke="currentColor" stroke-width="2" />
            <path d="M9 15v7c4 3 10 3 14 0v-7M27 12v10" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
          </svg>
        </span>
        <span>my-campus</span>
      </a>
      <div class="header-meta">
        <span class="header-caption">校园服务智能体</span>
        <span class="version-pill">v0.1.0</span>
      </div>
    </header>

    <main class="bootstrap-main">
      <section class="intro" aria-labelledby="page-title">
        <p class="eyebrow"><span></span> 第一阶段 · 工程初始化</p>
        <h1 id="page-title">你好，<span>my-campus</span></h1>
        <p class="intro-description">校园服务，从这里开始。<br />基础工程已启动，连接状态一目了然。</p>
      </section>

      <section class="connection-card" aria-labelledby="connection-title">
        <div class="card-heading">
          <div class="section-heading">
            <span class="section-icon"><el-icon :size="22"><Connection /></el-icon></span>
            <div>
              <h2 id="connection-title">服务连接</h2>
              <p>检查前端与后端的通信状态</p>
            </div>
          </div>
          <el-button :icon="RefreshRight" :loading="state === 'checking'" @click="refreshHealth">
            {{ state === 'checking' ? '检查中' : '重新检查' }}
          </el-button>
        </div>

        <div class="service-row">
          <div class="service-name"><span class="service-dot is-online"></span><strong>前端应用</strong></div>
          <span class="service-description">my-campus · v0.1.0</span>
          <el-tag type="success" effect="light" round>已运行</el-tag>
        </div>
        <div class="service-row">
          <div class="service-name"><span class="service-dot" :class="`is-${state}`"></span><strong>后端服务</strong></div>
          <span class="service-description">{{ health ? `${health.name} · v${health.version}` : 'GET /api/health' }}</span>
          <el-tag :type="statusType" effect="light" round>{{ statusLabel }}</el-tag>
        </div>

        <div class="health-message" :class="`message-${state}`" role="status" aria-live="polite">
          <el-icon :size="18" :class="{ 'checking-icon': state === 'checking' }">
            <Check v-if="state === 'online'" />
            <RefreshRight v-else-if="state === 'checking'" />
            <Warning v-else />
          </el-icon>
          <span>{{ message }}</span>
        </div>

        <div class="connection-details">
          <span>服务地址 <code>{{ healthEndpoint }}</code></span>
          <span v-if="checkedAt">最近检查 {{ checkedAt }}</span>
        </div>
      </section>

      <div class="stage-note">
        <span class="note-icon"><el-icon :size="18"><ArrowRight /></el-icon></span>
        <p>当前交付工程基础，校园业务将在后续阶段逐步加入。</p>
      </div>
    </main>

    <footer class="site-footer">
      <span>my-campus</span>
      <span>工程初始化 · v0.1.0</span>
    </footer>
  </div>
</template>

<style src="./style.css"></style>
