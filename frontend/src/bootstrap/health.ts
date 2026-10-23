export interface HealthData {
  name: 'my-campus'
  version: string
  status: 'ok'
}

export type HealthResult =
  | { state: 'online'; data: HealthData; message: string }
  | { state: 'offline' | 'incompatible'; message: string }

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
export const healthEndpoint = `${apiBase}/api/health`

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function readHealthData(value: unknown): HealthData | null {
  if (!isRecord(value) || value.code !== 200 || value.message !== 'ok') return null
  const data = value.data
  if (
    !isRecord(data) ||
    data.name !== 'my-campus' ||
    typeof data.version !== 'string' ||
    !data.version.trim() ||
    data.status !== 'ok'
  ) {
    return null
  }
  return { name: data.name, version: data.version, status: data.status }
}

export async function checkBackendHealth(signal: AbortSignal): Promise<HealthResult> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal.addEventListener('abort', abort, { once: true })
  if (signal.aborted) controller.abort()
  const timeout = window.setTimeout(abort, 5000)

  try {
    const response = await fetch(healthEndpoint, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
      credentials: 'omit',
      cache: 'no-store'
    })
    if (!response.ok) {
      return {
        state: 'offline',
        message: `后端返回 HTTP ${response.status}，请检查服务启动状态。`
      }
    }

    let payload: unknown
    try {
      payload = await response.json()
    } catch (error) {
      if (controller.signal.aborted) throw error
      return { state: 'incompatible', message: '接口已响应，但未返回有效的 JSON 数据。' }
    }
    const data = readHealthData(payload)
    return data
      ? { state: 'online', data, message: '健康检查通过，前后端已成功连接。' }
      : { state: 'incompatible', message: '接口已响应，但返回内容与 my-campus 健康接口约定不一致。' }
  } catch {
    return {
      state: 'offline',
      message: controller.signal.aborted
        ? '连接在 5 秒内未完成，请检查后端是否已启动。'
        : '暂时无法连接后端，请检查服务地址和本地运行状态。'
    }
  } finally {
    window.clearTimeout(timeout)
    signal.removeEventListener('abort', abort)
  }
}
