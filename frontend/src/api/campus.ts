import { request } from '../utils/campus-request'

export type Role = 'student' | 'teacher' | 'admin'

export interface CampusUser {
  id: number
  username: string
  name: string
  role: Role
  email: string | null
  phone: string | null
  avatar: string | null
  status: number
}

export interface Credentials { username: string; password: string }
export interface LoginData { token: string; user: CampusUser }
export interface UserPage { list: CampusUser[]; total: number }
export interface ProfileData { name: string; email: string | null; phone: string | null }
export interface AdminUserData extends ProfileData { role: Role; status: number }
export interface CreateUserData extends AdminUserData { username: string; password: string }

export const loginApi = (data: Credentials) =>
  request<LoginData>({ method: 'POST', url: '/auth/login', data }, false)
export const registerApi = (data: Credentials & { name?: string }) =>
  request<CampusUser>({ method: 'POST', url: '/auth/register', data }, false)
export const logoutApi = () => request<null>({ method: 'POST', url: '/auth/logout' })
export const currentUserApi = () => request<CampusUser>({ url: '/user/me' })
export const updateProfileApi = (data: ProfileData) =>
  request<CampusUser>({ method: 'PATCH', url: '/user/me', data })
export const updatePasswordApi = (data: { old_password: string; new_password: string }) =>
  request<null>({ method: 'POST', url: '/user/me/password', data })
export const listUsersApi = (params: { q: string; page: number; page_size: number }) =>
  request<UserPage>({ url: '/admin/users', params })
export const createUserApi = (data: CreateUserData) =>
  request<CampusUser>({ method: 'POST', url: '/admin/users', data })
export const updateUserApi = (id: number, data: AdminUserData) =>
  request<CampusUser>({ method: 'PATCH', url: `/admin/users/${id}`, data })
