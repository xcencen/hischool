<template>
  <div>
    <el-card>
      <template #header>
        <div style="font-size: 16px; font-weight: bold">学习计划</div>
      </template>
      <el-form @submit.prevent>
        <el-input
          v-model="content"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          placeholder="填写一段学习计划并保存（预习 / 复习均可）"
        >
        </el-input>
        <div style="margin-top: 10px">
          <el-button type="primary" :loading="saving" @click="handleSave">保存计划</el-button>
        </div>
      </el-form>
      <el-divider />
      <el-table
        :data="tableData"
        v-loading="loading"
        :header-cell-style="{ backgroundColor: '#f5f7fa', color: '#333' }"
      >
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="计划内容" min-width="280">
          <template #default="{ row }">
            <div class="plan-preview">{{ previewText(row.content) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openDetail(row)">查看</el-button>
            <el-button type="danger" link @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top: 10px; display: flex; justify-content: flex-end">
        <el-pagination
          v-model:current-page="params.page"
          v-model:page-size="params.pageSize"
          :total="total"
          background
          layout="total, prev, pager, next"
          @current-change="load"
        >
        </el-pagination>
      </div>
    </el-card>
    <el-dialog v-model="detailVisible" title="计划详情" width="50%" destroy-on-close>
      <div class="detail-meta">创建时间：{{ formatTime(detailRow?.create_time) }}</div>
      <div class="plan-md" v-html="parseMarkdown(detailRow?.content)"></div>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'StudyPlan' })
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { createStudyPlan, deleteStudyPlan, listStudyPlans } from '@/api/studyPlan'

marked.setOptions({
  gfm: true,
  breaks: true
})

const content = ref('')
const saving = ref(false)
const loading = ref(false)
const params = reactive({
  page: 1,
  pageSize: 10
})
const tableData = ref([])
const total = ref(0)
const detailVisible = ref(false)
const detailRow = ref(null)

const parseMarkdown = (text) => {
  if (!text) return ''
  const rawHtml = marked.parse(String(text).replace(/\r\n/g, '\n'))
  return DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } })
}

const previewText = (text, maxLen = 120) => {
  if (!text) return '-'
  const plain = String(text)
    .replace(/\r\n/g, '\n')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\|/g, ' ')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_~`>#\-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!plain) return '-'
  return plain.length > maxLen ? `${plain.slice(0, maxLen)}…` : plain
}

const formatTime = (value) => {
  if (!value) return '-'
  const text = String(value).replace('T', ' ')
  return text.length >= 19 ? text.slice(0, 19) : text
}

const openDetail = (row) => {
  detailRow.value = row
  detailVisible.value = true
}

const load = async () => {
  loading.value = true
  try {
    const res = await listStudyPlans({
      page: params.page,
      page_size: params.pageSize
    })
    if (res.code === 200) {
      tableData.value = res.data?.list || []
      total.value = res.data?.total || 0
    }
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  if (!content.value.trim()) {
    ElMessage.warning('请填写计划内容')
    return
  }
  saving.value = true
  try {
    const res = await createStudyPlan(content.value.trim())
    if (res.code === 200) {
      ElMessage.success('已保存')
      content.value = ''
      params.page = 1
      await load()
    }
  } finally {
    saving.value = false
  }
}

const handleDelete = (row) => {
  ElMessageBox.confirm('确认删除这条学习计划？', '确认删除', { type: 'warning' }).then(
    async () => {
      const res = await deleteStudyPlan(row.id)
      if (res.code === 200) {
        ElMessage.success('已删除')
        await load()
      }
    }
  )
}

onMounted(() => {
  load()
})
</script>
<style scoped>
.plan-preview {
  line-height: 1.5;
  color: #606266;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}
.detail-meta {
  margin-bottom: 12px;
  color: #909399;
  font-size: 13px;
}
.plan-md {
  line-height: 1.6;
  overflow-x: auto;
  max-height: 60vh;
  overflow-y: auto;
  padding: 4px 0;
}
.plan-md :deep(p) {
  margin: 0.35em 0;
}
.plan-md :deep(ul),
.plan-md :deep(ol) {
  margin: 0.35em 0;
  padding-left: 1.3em;
}
</style>
