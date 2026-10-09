/**
 * 剧本相关 API
 * 提供生成剧本、获取剧本、更新剧本接口
 * @file api/script.ts
 */

import request from './request'
import type { Script } from '@/types'

/** 生成剧本请求参数 */
export interface GenerateScriptParams {
  /** 主题/故事提示词 */
  prompt: string
  /** 风格 */
  style?: string
  /** 集数 */
  episodes?: number
}

/** 更新剧本请求参数 */
export interface UpdateScriptParams {
  /** 剧本标题 */
  title?: string
  /** 剧本正文 */
  content?: string
}

/**
 * 生成剧本
 * @param id - 项目 ID
 * @param data - 生成参数
 * @returns 生成的剧本信息
 */
export function generateScript(id: string, data: GenerateScriptParams): Promise<Script> {
  return request.post(`/projects/${id}/script/generate`, data)
}

/**
 * 获取项目剧本
 * @param id - 项目 ID
 * @returns 剧本信息
 */
export function getScript(id: string): Promise<Script> {
  return request.get(`/projects/${id}/script`)
}

/**
 * 更新剧本
 * @param id - 项目 ID
 * @param data - 更新参数
 * @returns 更新后的剧本信息
 */
export function updateScript(id: string, data: UpdateScriptParams): Promise<Script> {
  return request.put(`/projects/${id}/script`, data)
}

/**
 * 确认剧本，推进到资产阶段
 * @param id - 项目 ID
 * @returns 空响应
 */
export function confirmScript(id: string): Promise<void> {
  return request.post(`/projects/${id}/script/confirm`)
}

/** 剧本质量评分结果（SCR-07） */
export interface ScriptScore {
  /** 综合总分（0-100） */
  overall: number
  /** 冲突强度（0-100） */
  conflict: number
  /** 人物弧光（0-100） */
  character: number
  /** 节奏把控（0-100） */
  pacing: number
  /** 爽点密度（0-100） */
  hook_density: number
  /** 改进建议列表 */
  suggestions?: string[]
  /** 一句话评语 */
  summary?: string
  /** 是否为兜底估算评分（LLM 输出解析失败时为 true） */
  estimated?: boolean
}

/**
 * 获取剧本质量评分（LLM 四维评分 + 总分 + 建议）
 * @param id - 项目 ID
 * @returns 评分结果
 */
export function scoreScript(id: string): Promise<ScriptScore> {
  return request.post(`/projects/${id}/script/score`)
}
