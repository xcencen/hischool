import { request } from '../utils/campus-request'

export type ContentKind = 'notices' | 'activities'
export type PublicationState = 'draft' | 'pending' | 'published' | 'rejected'
export interface Page<T> { list: T[]; total: number }
export interface Category { id: number; code: string; name: string; status: number }
export interface Notice {
  id: number; code: string; title: string; content: string; category_id: number
  category_name: string; publisher_name: string; published_at: string | null
}
export interface Activity {
  id: number; code: string; title: string; content: string; publisher_name: string
  published_at: string | null; location: string; start_time: string; end_time: string
  registration_deadline: string; capacity: number; enrolled_count: number
  registration_status: string | null; can_register: boolean; can_cancel: boolean
}
export interface ManagedContent {
  id: number; code: string; title: string; content: string; publisher_name: string
  owner_id: number; state: PublicationState; revision: number; review_note: string | null
  published_at: string | null; category_id?: number; category_name?: string
  location?: string; start_time?: string; end_time?: string; registration_deadline?: string
  capacity?: number; enrolled_count?: number
}
export interface Registration {
  id: number; activity_id: number; status: 'registered' | 'cancelled'; registered_at: string
  cancelled_at: string | null; activity_title: string; activity_published: boolean
  start_time: string; location: string | null; can_cancel: boolean
}
export interface ListParams { page: number; page_size: number; q?: string; category_id?: number }
export interface PublicationInput {
  code?: string; title: string; content: string; state: string; category_id?: number
  location?: string; start_time?: string; end_time?: string; registration_deadline?: string; capacity?: number
}
export const stateLabel = (state: string) =>
  ({ draft: '草稿', pending: '待审核', published: '已发布', rejected: '已退回' }[state] ?? state)
export const categoriesApi = (admin = false) =>
  request<Category[]>({ url: admin ? '/admin/notice-categories' : '/notice-categories' })
export const saveCategoryApi = (data: { code?: string; name: string; status: number }, id?: number) =>
  request<Category>({ method: id ? 'PATCH' : 'POST', url: '/admin/notice-categories' + (id ? `/${id}` : ''), data })
export const deleteCategoryApi = (id: number) => request<null>({ method: 'DELETE', url: `/admin/notice-categories/${id}` })
export const noticesApi = (params: ListParams) => request<Page<Notice>>({ url: '/notices', params })
export const noticeApi = (id: number) => request<Notice>({ url: `/notices/${id}` })
export const activitiesApi = (params: ListParams) => request<Page<Activity>>({ url: '/activities', params })
export const activityApi = (id: number) => request<Activity>({ url: `/activities/${id}` })
export const registerActivityApi = (id: number) =>
  request<Registration>({ method: 'POST', url: `/activities/${id}/registrations` })
export const cancelActivityApi = (id: number) =>
  request<Registration>({ method: 'POST', url: `/activities/${id}/registrations/cancel` })
export const registrationsApi = (params: { page: number; page_size: number }) =>
  request<Page<Registration>>({ url: '/user/me/registrations', params })
const managementPath = (kind: ContentKind, own: boolean) => `/${own ? 'owned' : 'admin'}/${kind}`
export const manageListApi = (kind: ContentKind, own: boolean, params: ListParams) =>
  request<Page<ManagedContent>>({ url: managementPath(kind, own), params })
export const manageDetailApi = (kind: ContentKind, own: boolean, id: number) =>
  request<ManagedContent>({ url: `${managementPath(kind, own)}/${id}` })
export const saveContentApi = (kind: ContentKind, own: boolean, data: PublicationInput, id?: number) =>
  request<ManagedContent>({ method: id ? 'PATCH' : 'POST', url: managementPath(kind, own) + (id ? `/${id}` : ''), data })
export const deleteContentApi = (kind: ContentKind, own: boolean, id: number) =>
  request<null>({ method: 'DELETE', url: `${managementPath(kind, own)}/${id}` })
export const reviewContentApi = (kind: ContentKind, id: number, data: { expected_revision: number; action: 'publish' | 'reject'; note: string }) =>
  request<ManagedContent>({ method: 'POST', url: `/admin/${kind}/${id}/review`, data })
