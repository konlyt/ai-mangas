/**
 * 通知状态管理 Store
 * 管理全局通知列表，提供推送、移除、清空通知等方法
 * @file stores/notification.ts
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 通知级别 */
export type NotificationType = 'success' | 'warning' | 'info' | 'error'

/** 通知项结构 */
export interface NotificationItem {
  /** 唯一 ID */
  id: string
  /** 通知类型 */
  type: NotificationType
  /** 通知标题 */
  title: string
  /** 通知内容 */
  message?: string
  /** 创建时间戳 */
  timestamp: number
}

/**
 * 通知 Store
 */
export const useNotificationStore = defineStore('notification', () => {
  /** 通知列表 */
  const notifications = ref<NotificationItem[]>([])

  /**
   * 推送一条通知
   * @param item - 通知内容
   */
  function push(item: Omit<NotificationItem, 'id' | 'timestamp'>): void {
    notifications.value.unshift({
      ...item,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      timestamp: Date.now(),
    })
  }

  /**
   * 移除指定通知
   * @param id - 通知 ID
   */
  function remove(id: string): void {
    notifications.value = notifications.value.filter((n) => n.id !== id)
  }

  /**
   * 清空所有通知
   */
  function clear(): void {
    notifications.value = []
  }

  return {
    notifications,
    push,
    remove,
    clear,
  }
})
