import { ApiError, request } from '../utils/campus-request'
import { readToken, storeToken } from '../utils/session-storage'

export interface KnowledgeStatus {
  configured: boolean
  ready: boolean
  model: string
  dimensions: number
  document_count: number
  chunk_count: number
  index_version: string | null
  message: string
}

export interface KnowledgeDocument {
  id: number
  title: string
  category: 'faq' | 'regulations' | 'guide'
  version: number
  page_count: number
  chunk_count: number
  status: string
  warnings: string[]
}

export interface KnowledgeHit {
  chunk_id: number
  document_id: number
  document_title: string
  version: number
  chapter: string
  page_number: number
  page_label: string | null
  content: string
  score: number
}

export interface KnowledgeSearchResult {
  query: string
  index_version: string
  results: KnowledgeHit[]
  insufficient: boolean
  message: string
}

export const knowledgeStatusApi = () => request<KnowledgeStatus>({ url: '/knowledge/status' })
export const knowledgeDocumentsApi = () => request<KnowledgeDocument[]>({ url: '/knowledge/documents' })
export const knowledgeSearchApi = (query: string, top_k: number) =>
  request<KnowledgeSearchResult>({ method: 'POST', url: '/knowledge/search', data: { query, top_k }, timeout: 60000 })

export async function fetchKnowledgeSource(documentId: number, version: number): Promise<Blob> {
  if (!Number.isSafeInteger(documentId) || documentId < 1 || !Number.isSafeInteger(version) || version < 1) {
    throw new ApiError('原文编号或版本无效。', 400)
  }
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
  const currentToken = readToken()
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 30000)
  try {
    const response = await fetch(`${base}/api/knowledge/documents/${documentId}/source?version=${version}`, {
      headers: currentToken ? { Authorization: `Bearer ${currentToken}` } : {},
      signal: controller.signal
    })
    if (!response.ok) {
      if (response.status === 401 && currentToken && currentToken === readToken()) {
        storeToken('')
        window.dispatchEvent(new Event('campus:session-expired'))
      }
      let message = response.status === 404 ? '原文不存在、版本不可用或资料已停用。' : '原文暂时无法加载，请稍后重试。'
      if (response.headers.get('content-type')?.includes('application/json')) {
        const body: unknown = await response.json().catch(() => null)
        if (body && typeof body === 'object' && 'message' in body && typeof body.message === 'string') {
          message = body.message
        }
      }
      throw new ApiError(message, response.status)
    }
    if (currentToken !== readToken()) throw new ApiError('登录状态已变化，请重新打开原文。', 401)
    const source = await response.blob()
    if (currentToken !== readToken()) throw new ApiError('登录状态已变化，请重新打开原文。', 401)
    const mime = source.type.split(';')[0]?.trim() ?? ''
    if (!['application/pdf', 'text/plain', 'text/markdown', 'application/octet-stream'].includes(mime)) {
      throw new ApiError('原文格式无法安全展示。', 502)
    }
    return source
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('原文加载超时，请稍后重试。', 0)
    }
    throw new ApiError('无法连接原文服务，请检查网络后重试。', 0)
  } finally {
    window.clearTimeout(timeout)
  }
}
