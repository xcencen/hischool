import request from '@/utils/request'

/** 课表分页列表：学生查自己；管理员可传 user_id / date；返回 list + total */
export function listSchedulesApi(params = {}) {
  return request({
    url: '/api/schedules',
    method: 'get',
    params
  })
}

export function createScheduleApi(data) {
  return request({
    url: '/api/schedules',
    method: 'post',
    data
  })
}

export function updateScheduleApi(id, data) {
  return request({
    url: `/api/schedules/${id}`,
    method: 'put',
    data
  })
}

export function deleteScheduleApi(id) {
  return request({
    url: `/api/schedules/${id}`,
    method: 'delete'
  })
}
