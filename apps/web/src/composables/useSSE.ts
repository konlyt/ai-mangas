/**
 * SSE（Server-Sent Events）封装
 * 基于 fetch + ReadableStream 实现，支持 POST 方法、自定义请求头和请求体，
 * 解决原生 EventSource 仅支持 GET 且无法携带认证头的限制。
 * @file composables/useSSE.ts
 */

/** SSE 请求选项 */
export interface SseRequestOptions {
  /** HTTP 方法，默认 POST */
  method?: 'GET' | 'POST' | 'PUT'
  /** 请求头 */
  headers?: Record<string, string>
  /** 请求体（对象将自动 JSON 序列化） */
  body?: unknown
}

/** 消息回调类型 */
export type SseMessageHandler = (data: string) => void
/** 错误回调类型 */
export type SseErrorHandler = (error: Error) => void

/**
 * SSE 连接管理 Hook
 * @returns start 与 stop 方法
 */
export function useSSE() {
  /** AbortController 用于中断 fetch 请求 */
  let abortController: AbortController | null = null
  /** 是否处于手动停止状态 */
  let stopped = true

  /**
   * 启动 SSE 连接
   * @param url - SSE 服务地址
   * @param onMessage - 消息回调（接收解析后的 data 字符串）
   * @param onError - 错误回调
   * @param options - 请求选项（方法、头、体）
   */
  async function start(
    url: string,
    onMessage: SseMessageHandler,
    onError?: SseErrorHandler,
    options?: SseRequestOptions,
  ): Promise<void> {
    stopped = false
    cleanup()

    abortController = new AbortController()

    try {
      const response = await fetch(url, {
        method: options?.method || 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(options?.headers || {}),
        },
        body: options?.body ? JSON.stringify(options.body) : undefined,
        signal: abortController.signal,
      })

      if (!response.ok || !response.body) {
        throw new Error(`SSE 请求失败：HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        // SSE 事件以 \n\n 分隔
        const events = buffer.split('\n\n')
        // 最后一段可能不完整，保留到 buffer
        buffer = events.pop() || ''

        for (const event of events) {
          if (stopped) break
          // 提取 data: 行的内容
          const dataLines = event
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trim())
          if (dataLines.length > 0) {
            onMessage(dataLines.join('\n'))
          }
        }
      }
    } catch (err) {
      if (!stopped) {
        onError?.(err instanceof Error ? err : new Error(String(err)))
      }
    }
  }

  /**
   * 关闭连接并清理资源
   */
  function cleanup(): void {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }

  /**
   * 停止 SSE 连接
   */
  function stop(): void {
    stopped = true
    cleanup()
  }

  return {
    start,
    stop,
  }
}
