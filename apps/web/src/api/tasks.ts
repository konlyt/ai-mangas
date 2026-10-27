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

/** 后端任务终态枚举（GET /tasks/{id}/status 轻量端点返回的原始状态值） */
export type BackendTaskStatus = 'queued' | 'running' | 'done' | 'failed' | 'dead'

/**
 * 任务状态查询结果
 * 对齐 GET /tasks/{task_id}/status 响应 data（轻量字段，画布生成轮询用）
 */
export interface TaskStatusResult {
  /** 任务 ID */
  task_id: number
  /** 任务状态（后端原始枚举：queued/running/done/failed/dead） */
  status: BackendTaskStatus
  /** 进度百分比（done=100 / running=50 / 其余 0） */
  progress: number
  /** 错误信息；done 时可能携带 "ref_dropped: ..." 降级标记（参考图被丢弃，任务仍成功） */
  error_message: string | null
}

/**
 * 查询任务状态（轻量端点，仅返回状态相关字段，画布节点生成轮询使用）
 * @param id - 任务 ID
 * @returns 任务状态 {task_id, status, progress, error_message}
 */
export function getTaskStatus(id: number | string): Promise<TaskStatusResult> {
  return request.get(`/tasks/${id}/status`)
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
