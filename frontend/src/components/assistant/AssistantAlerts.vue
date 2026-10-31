<script setup lang="ts">
import type { AssistantAlert } from '../../api/assistant'
defineProps<{ alerts: AssistantAlert[]; total: number; loading: boolean; error: string; pending: number | null }>()
defineEmits<{ ack: [id: number]; more: []; refresh: [] }>()
const titles = { threshold: '额度接近上限', limit: '额度不足', overrun: '实际用量超过预留', unknown_usage: '用量尚未确认' }
</script>

<template>
  <section class="assistant-alerts" aria-label="预算告警">
    <div class="alert-heading"><strong>预算告警</strong><el-button text size="small" :loading="loading" @click="$emit('refresh')">刷新告警</el-button></div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!alerts.length && !loading">暂无告警</p>
    <div class="alert-list">
      <article v-for="alert in alerts" :key="alert.id">
        <strong>{{ titles[alert.kind] || '预算状态变化' }}</strong>
        <span>{{ alert.day }} · {{ alert.scope === 'global' ? '全局' : alert.scope === 'run' ? '本次运行' : '个人' }}</span>
        <p>记录金额 ¥ {{ alert.amount }} / 限额 ¥ {{ alert.cap }}</p>
        <p v-if="alert.kind === 'unknown_usage'">费用按调用预留上界估算，最终以供应商账单为准。</p>
        <span v-if="alert.acknowledged">已读</span>
        <el-button v-else size="small" :loading="pending === alert.id" :disabled="pending !== null" @click="$emit('ack', alert.id)">标为已读</el-button>
      </article>
    </div>
    <el-button v-if="alerts.length < total" text :loading="loading" @click="$emit('more')">加载更多告警</el-button>
    <small>标为已读不会解除额度限制；阈值包含在途预留。</small>
  </section>
</template>

<style scoped>
.assistant-alerts { margin: 0 0 16px; padding: 12px 16px; border: 1px solid #e5eaf4; border-radius: 10px; font-size: 12px; color: #53657f; }
.alert-heading { display: flex; justify-content: space-between; align-items: center; }
.alert-list { max-height: 180px; overflow-y: auto; }
article { border-top: 1px solid #e5eaf4; padding: 10px 0; } article > span { margin-left: 12px; }
p { margin: 7px 0; } small { display: block; margin-top: 8px; }
</style>
