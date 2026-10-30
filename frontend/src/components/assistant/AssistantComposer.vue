<script setup lang="ts">
const props = defineProps<{ modelValue: string; disabled: boolean; canSend: boolean; submitting: boolean; running: boolean; cancelling: boolean; hint: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; send: []; stop: [] }>()
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault()
    if (props.canSend) emit('send')
  }
}
</script>

<template>
  <form class="assistant-composer" @submit.prevent="emit('send')">
    <label for="assistant-input">发送消息</label>
    <el-input id="assistant-input" :model-value="modelValue" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" maxlength="4000" show-word-limit placeholder="输入校园问题，Enter 发送，Shift + Enter 换行" :disabled="disabled" @update:model-value="emit('update:modelValue', $event)" @keydown="onKeydown" />
    <div class="assistant-composer-footer"><p>{{ hint }}</p><el-button v-if="running" :loading="cancelling" :disabled="cancelling" @click="emit('stop')">停止运行</el-button><el-button v-else type="primary" native-type="submit" :loading="submitting" :disabled="!canSend">发送消息 ↑</el-button></div>
  </form>
</template>

<style scoped>
.assistant-composer { border-top: 1px solid #edf0f7; padding: 18px 24px 15px; background: #fff; flex: 0 0 auto; }.assistant-composer label { display: block; font-size: 12px; color: #637691; margin-bottom: 10px; font-weight: 600; }.assistant-composer :deep(.el-textarea__inner) { background: #fafbfe; box-shadow: 0 0 0 1px #e7ecf5 inset; padding: 12px 15px 22px; line-height: 1.8; border-radius: 10px; font-size: 13px; }.assistant-composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 13px; margin-top: 13px; }.assistant-composer-footer p { margin: 0; color: #96a2b4; font-size: 11px; line-height: 1.7; }.assistant-composer-footer .el-button { flex-shrink: 0; }@media (max-width: 760px) { .assistant-composer { padding: 15px; }.assistant-composer-footer { align-items: flex-end; }.assistant-composer-footer p { font-size: 10px; } }
</style>
