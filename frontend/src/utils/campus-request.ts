import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'
import { readToken, storeToken } from './session-storage'

interface Envelope<T> {
  code: number
  message: string
  data: T
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

const base = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
const client = axios.create({ baseURL: `${base}/api`, timeout: 12000 })

export async function request<T>(config: AxiosRequestConfig, authenticated = true): Promise<T> {
  const currentToken = authenticated ? readToken() : ''
  try {
    const response = await client.request<Envelope<T>>({
      ...config,
      headers: {
        ...config.headers,
        ...(currentToken ? { Authorization: `Bearer ${currentToken}` } : {})
      }
    })
    if (response.data.code !== 200) {
      throw new ApiError(response.data.message || '请求未完成，请稍后重试。', response.data.code)
    }
    return response.data.data
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (axios.isAxiosError<Envelope<unknown>>(error)) {
      const status = error.response?.status ?? 0
      if (status === 401 && currentToken && currentToken === readToken()) {
        storeToken('')
        window.dispatchEvent(new Event('campus:session-expired'))
      }
      throw new ApiError(
        error.response?.data?.message || (status ? '请求失败，请稍后重试。' : '无法连接服务，请检查网络后重试。'),
        status
      )
    }
    throw new ApiError('请求失败，请稍后重试。', 0)
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}
