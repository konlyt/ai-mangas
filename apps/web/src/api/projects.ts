/**
 * 项目相关 API
 * 提供项目列表、创建、详情、更新、删除、最近项目、项目统计等接口
 * @file api/projects.ts
 */

import request from './request'
import type {
  Project,
  CreateProjectParams,
  UpdateProjectParams,
  ProjectStats,
  PageParams,
  PageResult,
} from '@/types'

/**
 * 获取项目列表（分页）
 * @param params - 分页查询参数
 * @returns 分页项目列表
 */
export function listProjects(params?: PageParams): Promise<PageResult<Project>> {
  return request.get('/projects', { params })
}

/**
 * 创建新项目
 * @param data - 创建项目参数
 * @returns 新建的项目信息
 */
export function createProject(data: CreateProjectParams): Promise<Project> {
  return request.post('/projects', data)
}

/**
 * 获取项目详情
 * @param id - 项目 ID
 * @returns 项目详情
 */
export function getProject(id: string): Promise<Project> {
  return request.get(`/projects/${id}`)
}

/**
 * 更新项目
 * @param id - 项目 ID（Project.id 为 number，兼容传入字符串形式）
 * @param data - 更新参数
 * @returns 更新后的项目信息
 */
export function updateProject(id: number | string, data: UpdateProjectParams): Promise<Project> {
  return request.put(`/projects/${id}`, data)
}

/**
 * 删除项目
 * @param id - 项目 ID（Project.id 为 number，兼容传入字符串形式）
 * @returns 空响应
 */
export function deleteProject(id: number | string): Promise<void> {
  return request.delete(`/projects/${id}`)
}

/**
 * 获取最近访问的项目列表
 * @returns 最近项目列表
 */
export function recentProjects(): Promise<Project[]> {
  return request.get('/projects/recent')
}

/**
 * 获取项目统计信息
 * @returns 项目统计数据
 */
export function projectStats(): Promise<ProjectStats> {
  return request.get('/projects/stats')
}
