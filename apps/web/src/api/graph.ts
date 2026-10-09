/**
 * 工作流图（Graph）相关 API
 * 提供运行工作流、获取工作流状态、恢复工作流等接口
 * @file api/graph.ts
 */

import request from './request'

/** 运行工作流请求参数 */
export interface RunGraphParams {
  /** 工作流节点名称 */
  node?: string
  /** 输入数据 */
  input?: Record<string, unknown>
}

/** 工作流状态 */
export interface GraphState {
  /** 工作流运行 ID */
  run_id: string
  /** 当前状态 */
  status: 'idle' | 'running' | 'waiting' | 'success' | 'failed'
  /** 已执行的节点列表 */
  executed_nodes: string[]
  /** 当前节点 */
  current_node?: string
  /** 节点输出数据 */
  outputs: Record<string, unknown>
}

/**
 * 运行工作流图
 * @param id - 项目 ID
 * @param data - 运行参数
 * @returns 工作流运行状态
 */
export function runGraph(id: string, data: RunGraphParams): Promise<GraphState> {
  return request.post(`/projects/${id}/graph/run`, data)
}

/**
 * 获取工作流运行状态
 * @param id - 项目 ID
 * @returns 工作流状态
 */
export function getGraphState(id: string): Promise<GraphState> {
  return request.get(`/projects/${id}/graph/state`)
}

/**
 * 恢复暂停的工作流（处理 human-in-the-loop）
 * @param id - 项目 ID
 * @param data - 恢复参数（用户输入等）
 * @returns 工作流状态
 */
export function resumeGraph(id: string, data: Record<string, unknown>): Promise<GraphState> {
  return request.post(`/projects/${id}/graph/resume`, data)
}
