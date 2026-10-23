<template>
  <div>
    <el-card>
      <template #header>
        <div style="font-size: 16px; font-weight: bold">课表管理</div>
      </template>
      <div style="margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 8px">
        <el-select
          v-model="params.userId"
          placeholder="按用户查看"
          clearable
          filterable
          style="width: 220px"
          @change="handleSearch"
          @clear="handleSearch"
        >
          <el-option
            v-for="u in studentOptions"
            :key="u.id"
            :label="`${u.name}（${u.username}）`"
            :value="u.id"
          />
        </el-select>
        <el-date-picker
          v-model="params.date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="按日期筛选"
          clearable
          @change="handleSearch"
          @clear="handleSearch"
        >
        </el-date-picker>
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button type="success" :icon="Plus" @click="handleCreate">新增课表</el-button>
      </div>
      <el-table
        v-loading="loading"
        :header-cell-style="{ backgroundColor: '#f5f7fa', color: '#333' }"
        :data="tableData"
        style="width: 100%"
      >
        <el-table-column label="学生" min-width="140">
          <template #default="{ row }"> {{ row.user_name }}（{{ row.username }}） </template>
        </el-table-column>
        <el-table-column prop="class_date" label="日期" width="120" />
        <el-table-column prop="period" label="节次" width="110" />
        <el-table-column prop="course_name" label="课程" min-width="140" />
        <el-table-column prop="location" label="地点" min-width="120" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" text bg @click="handleEdit(row)">编辑</el-button>
            <el-button type="danger" text bg @click="handleDelete(row)">删除</el-button>
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
    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? '编辑课表' : '新增课表'"
      width="480"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        style="padding-right: 20px; padding-top: 8px"
      >
        <el-form-item label="学生" prop="user_id">
          <el-select v-model="form.user_id" placeholder="选择学生" filterable style="width: 100%">
            <el-option
              v-for="u in studentOptions"
              :key="u.id"
              :label="`${u.name}（${u.username}）`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="课程" prop="course_id">
          <el-select v-model="form.course_id" placeholder="选择课程" filterable style="width: 100%">
            <el-option
              v-for="c in courseOptions"
              :key="c.id"
              :label="c.code ? `${c.name}（${c.code}）` : c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="上课日期" prop="class_date">
          <el-date-picker
            v-model="form.class_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            style="width: 100%"
          >
          </el-date-picker>
        </el-form-item>
        <el-form-item label="节次" prop="period">
          <el-input v-model="form.period" placeholder="例如：1-2 节" />
        </el-form-item>
        <el-form-item label="地点" prop="location">
          <el-input v-model="form.location" placeholder="例如：教学楼 A201" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="formLoading" @click="handleSave">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'ScheduleManage' })
import { Plus, Search } from '@element-plus/icons-vue'
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createScheduleApi,
  deleteScheduleApi,
  listSchedulesApi,
  updateScheduleApi
} from '@/api/schedule'
import { listCoursesApi } from '@/api/course'
import { getUserPageList } from '@/api/user'

const params = reactive({
  page: 1,
  pageSize: 10,
  userId: null,
  date: null
})
const loading = ref(false)
const tableData = ref([])
const total = ref(0)

const studentOptions = ref([])
const courseOptions = ref([])

const dialogVisible = ref(false)
const formRef = ref()
const formLoading = ref(false)
const form = reactive({
  id: null,
  user_id: null,
  course_id: null,
  class_date: '',
  period: '',
  location: ''
})

const rules = {
  user_id: [{ required: true, message: '请选择学生', trigger: 'change' }],
  course_id: [{ required: true, message: '请选择课程', trigger: 'change' }],
  class_date: [{ required: true, message: '请选择上课日期', trigger: 'change' }],
  period: [{ required: true, message: '请输入节次', trigger: 'blur' }],
  location: [{ required: true, message: '请输入地点', trigger: 'blur' }]
}

const resetForm = () => {
  Object.assign(form, {
    id: null,
    user_id: params.userId || null,
    course_id: null,
    class_date: '',
    period: '',
    location: ''
  })
}

const loadStudents = async () => {
  const res = await getUserPageList({ page: 1, page_size: 200 })
  if (res.code === 200) {
    studentOptions.value = (res.data?.list || []).filter((u) => u.role === 'student')
  }
}

const loadCourses = async () => {
  const res = await listCoursesApi()
  if (res.code === 200) {
    courseOptions.value = (res.data || []).filter((c) => c.status === 1)
  }
}

const load = async () => {
  loading.value = true
  try {
    const res = await listSchedulesApi({
      page: params.page,
      page_size: params.pageSize,
      user_id: params.userId || undefined,
      date: params.date || undefined
    })
    if (res.code === 200) {
      tableData.value = res.data?.list || []
      total.value = res.data?.total || 0
    }
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  params.page = 1
  load()
}

const handleCreate = () => {
  resetForm()
  dialogVisible.value = true
}

const handleEdit = (row) => {
  resetForm()
  Object.assign(form, {
    id: row.id,
    user_id: row.user_id,
    course_id: row.course_id,
    class_date: row.class_date,
    period: row.period,
    location: row.location
  })
  dialogVisible.value = true
}

const handleSave = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  formLoading.value = true
  try {
    const payload = {
      user_id: form.user_id,
      course_id: form.course_id,
      class_date: form.class_date,
      period: form.period,
      location: form.location
    }
    const res = form.id
      ? await updateScheduleApi(form.id, payload)
      : await createScheduleApi(payload)
    if (res.code === 200) {
      dialogVisible.value = false
      ElMessage.success('操作成功')
      load()
    }
  } finally {
    formLoading.value = false
  }
}

const handleDelete = (row) => {
  ElMessageBox.confirm(
    `确认删除「${row.user_name}」在 ${row.class_date} 的「${row.course_name}」课表？`,
    '确认删除',
    { type: 'warning' }
  ).then(async () => {
    const res = await deleteScheduleApi(row.id)
    if (res.code === 200) {
      ElMessage.success('已删除')
      load()
    }
  })
}

onMounted(async () => {
  await Promise.all([loadStudents(), loadCourses()])
  load()
})
</script>
