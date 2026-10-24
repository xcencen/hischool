<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { registrationsApi, cancelActivityApi } from '../api/community'
import type { Registration } from '../api/community'
import { displayDateTime } from '../utils/campus-date'
import { errorMessage } from '../utils/campus-request'
const rows = ref<Registration[]>([])
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const saving = ref<number | null>(null)
const error = ref('')
let sequence = 0
async function load() {
  const id = ++sequence
  loading.value = true
  error.value = ''
  try { const data = await registrationsApi({ page: page.value, page_size: 10 }); if (id === sequence) { rows.value = data.list; total.value = data.total } }
  catch (cause) { if (id === sequence) { rows.value = []; error.value = errorMessage(cause) } }
  finally { if (id === sequence) loading.value = false }
}
async function cancel(row: Registration) {
  try { await ElMessageBox.confirm('确认取消这条活动报名？', '取消报名', { confirmButtonText: '确认取消', cancelButtonText: '返回' }) }
  catch { return }
  saving.value = row.id
  try { await cancelActivityApi(row.activity_id); ElMessage.success('已取消报名'); await load() }
  catch (cause) { ElMessage.error(errorMessage(cause)); await load() }
  finally { saving.value = null }
}
onMounted(load)
</script>
<template>
  <section>
    <div class="campus-page-heading"><p class="campus-eyebrow">MY REGISTRATIONS</p><h1>我的报名记录</h1><p>查看本人活动报名与取消记录。</p></div>
    <div class="campus-table-card"><el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="campus-spaced" />
      <el-table v-loading="loading" :data="rows" empty-text="暂无报名记录"><el-table-column label="活动" min-width="170"><template #default="{ row }"><router-link v-if="row.activity_published" :to="`/app/activities/${row.activity_id}`" class="campus-card-link">{{ row.activity_title }}</router-link><span v-else>{{ row.activity_title }}</span></template></el-table-column><el-table-column label="开始时间" min-width="165"><template #default="{ row }">{{ displayDateTime(row.start_time) }}</template></el-table-column><el-table-column label="报名时间" min-width="165"><template #default="{ row }">{{ displayDateTime(row.registered_at) }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'registered' ? 'success' : 'info'" effect="plain">{{ row.status === 'registered' ? '已报名' : '已取消' }}</el-tag></template></el-table-column><el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="row.can_cancel" link type="primary" :loading="saving === row.id" :disabled="saving !== null && saving !== row.id" @click="cancel(row)">取消报名</el-button><span v-else class="campus-muted">—</span></template></el-table-column></el-table>
      <el-pagination v-if="total > 10" v-model:current-page="page" :total="total" :page-size="10" layout="prev, pager, next" class="campus-pagination" @current-change="load" />
    </div>
  </section>
</template>
