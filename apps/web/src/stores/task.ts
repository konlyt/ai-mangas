/**
 * 任务状态管理 Store
 * 管理后台任务列表、进行中任务数量，提供拉取、新增、更新任务等方法
 * @file stores/task.ts
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Task } from '@/types'
import { listTasks } from '@/api/tasks'

/**
 * 任务 Store
 */
export const useTaskStore = defineStore('task', () => {
  /** 任务列表 */
  const tasks = ref<Task[]>([])

  /** 进行中（pending + running + queued）任务数量 */
  const pendingCount = computed(() =>
    tasks.value.filter((t) => ['pending', 'running', 'queued'].includes(t.status)).length,
  )

  /**
   * 拉取任务列表
   */
  async function fetchTasks(): Promise<void> {
    const res = await listTasks({ page: 1, page_size: 50 })
    tasks.value = res.list
  }

  /**
   * 新增一个任务到列表头部
   * @param task - 任务对象
   */
  function addTask(task: Task): void {
    tasks.value.unshift(task)
  }

  /**
   * 更新任务信息
   * @param task - 更新后的任务对象
   */
  function updateTask(task: Task): void {
    const index = tasks.value.findIndex((t) => t.id === task.id)
    if (index !== -1) {
      tasks.value[index] = task
    } else {
      tasks.value.unshift(task)
    }
  }

  return {
    tasks,
    pendingCount,
    fetchTasks,
    addTask,
    updateTask,
  }
})
