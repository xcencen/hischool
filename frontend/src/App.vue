<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { tokenStorageKey } from './utils/session-storage'

const route = useRoute()
const router = useRouter()
function sessionExpired() {
  if (route.meta.requiresAuth) void router.replace({ path: '/login', query: { expired: '1' } })
}
function sessionChanged(event: StorageEvent) {
  if (event.key === tokenStorageKey && route.meta.requiresAuth) {
    // Clear all page memory when another tab changes the active identity.
    window.location.replace(router.resolve('/app').href)
  }
}
onMounted(() => {
  window.addEventListener('campus:session-expired', sessionExpired)
  window.addEventListener('storage', sessionChanged)
})
onBeforeUnmount(() => {
  window.removeEventListener('campus:session-expired', sessionExpired)
  window.removeEventListener('storage', sessionChanged)
})
</script>

<template>
  <div class="campus-app"><router-view /></div>
</template>
