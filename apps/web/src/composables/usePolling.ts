/**
 * 轮询封装
 * 按指定间隔定时执行回调函数，可随时停止
 * @file composables/usePolling.ts
 */

/**
 * 轮询管理 Hook
 * @returns start 与 stop 方法
 */
export function usePolling() {
  /** 轮询定时器 ID */
  let timer: number | null = null

  /**
   * 启动轮询
   * @param callback - 每次轮询执行的回调
   * @param interval - 轮询间隔（毫秒），默认 5000ms
   */
  function start(callback: () => void, interval = 5000): void {
    // 先立即执行一次
    callback()
    timer = window.setInterval(callback, interval)
  }

  /**
   * 停止轮询
   */
  function stop(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  return {
    start,
    stop,
  }
}
