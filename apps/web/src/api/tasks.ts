/**
 * 后台任务相关 API
 * 提供任务列表、SSE 流地址、重试、取消等接口
 * @file api/tasks.ts
 */

import request from './request'
import type { Task, PageParams, PageResult, TaskStatus, TaskType } from '@/types'

/** 任务列表查询参数 */
export interface TaskListParams extends PageParams {
  /** 按项目 ID 过滤 */
  project_id?: string
  /** 按任务类型过滤 */
  type?: TaskType
  /** 按任务状态过滤 */
  status?: TaskStatus
}

/**
 * 获取任务详情
 * @param id - 任务 ID
 * @returns 任务信息
 */
export function getTask(id: number | string): Promise<Task> {
  return request.get(`/tasks/${id}`)
}

/**
 * 获取任务列表（分页）
 * @param params - 查询参数
 * @returns 分页任务列表
 */
export function listTasks(params?: TaskListParams): Promise<PageResult<Task>> {
  return request.get('/tasks', { params })
}

/**
 * 获取任务的 SSE 事件流地址
 * @param id - 任务 ID
 * @returns SSE 流地址
 */
export function getTaskStreamUrl(id: string): Promise<{ url: string }> {
  return request.get(`/tasks/${id}/stream`)
}

/**
 * 重试失败的任务
 * @param id - 任务 ID
 * @returns 重试后的任务信息
 */
export function retryTask(id: string): Promise<Task> {
  return request.post(`/tasks/${id}/retry`)
}

/**
 * 取消运行中的任务
 * @param id - 任务 ID
 * @returns 空响应
 */
export function cancelTask(id: string): Promise<void> {
  return request.post(`/tasks/${id}/cancel`)
}
