import request from '@/utils/request'

/**
 * 课程列表（可按关键词模糊查询）
 */
export function listCoursesApi(params) {
  return request({
    url: '/api/courses',
    method: 'get',
    params
  })
}

/**
 * 课程详情
 */
export function getCourseApi(id) {
  return request({
    url: `/api/courses/${id}`,
    method: 'get'
  })
}

/**
 * 新增课程
 */
export function createCourseApi(data) {
  return request({
    url: '/api/courses',
    method: 'post',
    data
  })
}

/**
 * 修改课程
 */
export function updateCourseApi(id, data) {
  return request({
    url: `/api/courses/${id}`,
    method: 'put',
    data
  })
}

/**
 * 删除课程
 */
export function deleteCourseApi(id) {
  return request({
    url: `/api/courses/${id}`,
    method: 'delete'
  })
}
