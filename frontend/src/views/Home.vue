<template>
  <div>
    <el-card shadow="never">
      <div style="font-size: 18px; color: #333">欢迎您：{{ userInfo?.name || '同学' }}</div>
    </el-card>
  </div>
</template>

<script setup>
import { useUser } from '@/utils/user'
const { userInfo } = useUser()
</script>
