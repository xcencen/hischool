import { request } from '../utils/campus-request'

export interface Course {
  id: number
  code: string
  name: string
  teacher_id: number
  teacher_name: string
  description: string | null
  status: number
}
export interface PersonOption { id: number; name: string; username: string }
export interface CourseOptions { teachers: PersonOption[]; students: PersonOption[] }
export interface CourseInput { code: string; name: string; teacher_id: number; description: string | null; status: number }
export interface Lesson {
  id: number
  course_id: number
  course_name: string
  course_code: string
  teacher_id: number
  teacher_name: string
  class_date: string
  start_time: string
  end_time: string
  period: string
  location: string
}
export interface WeekSchedule { start_date: string; end_date: string; list: Lesson[] }
export type LessonInput = Pick<Lesson, 'course_id' | 'class_date' | 'start_time' | 'end_time' | 'period' | 'location'>

export const listCoursesApi = (q = '', admin = false) =>
  request<Course[]>({ url: admin ? '/admin/courses' : '/courses', params: { q } })
export const courseDetailApi = (id: number) => request<Course>({ url: `/courses/${id}` })
export const todayScheduleApi = (date: string) => request<Lesson[]>({ url: '/schedules/today', params: { date } })
export const weekScheduleApi = (date: string) => request<WeekSchedule>({ url: '/schedules/week', params: { date } })
export const courseOptionsApi = () => request<CourseOptions>({ url: '/admin/courses/options' })
export const createCourseApi = (data: CourseInput) => request<Course>({ method: 'POST', url: '/admin/courses', data })
export const updateCourseApi = (id: number, data: CourseInput) =>
  request<Course>({ method: 'PATCH', url: `/admin/courses/${id}`, data })
export const deleteCourseApi = (id: number) => request<null>({ method: 'DELETE', url: `/admin/courses/${id}` })
export const courseStudentsApi = (id: number) => request<PersonOption[]>({ url: `/admin/courses/${id}/students` })
export const saveCourseStudentsApi = (id: number, student_ids: number[]) =>
  request<PersonOption[]>({ method: 'PUT', url: `/admin/courses/${id}/students`, data: { student_ids } })
export const listLessonsApi = (params: { course_id?: number; date?: string }) =>
  request<Lesson[]>({ url: '/admin/schedules', params })
export const createLessonApi = (data: LessonInput) => request<Lesson>({ method: 'POST', url: '/admin/schedules', data })
export const updateLessonApi = (id: number, data: LessonInput) =>
  request<Lesson>({ method: 'PATCH', url: `/admin/schedules/${id}`, data })
export const deleteLessonApi = (id: number) => request<null>({ method: 'DELETE', url: `/admin/schedules/${id}` })
