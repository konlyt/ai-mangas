/**
 * 分镜相关 API
 * 提供生成分镜、获取分镜、更新分镜接口
 * @file api/storyboard.ts
 */

import request from './request'
import type { Storyboard, StoryboardUpdateParams } from '@/types'

/**
 * 根据剧本与资产生成分镜
 * @param id - 项目 ID
 * @returns 生成的分镜列表（Storyboard[]）
 */
export function generateStoryboard(id: string): Promise<Storyboard[]> {
  return request.post(`/projects/${id}/storyboard/generate`)
}

/**
 * 获取项目分镜列表
 * @param id - 项目 ID
 * @returns 分镜列表（Storyboard[]）
 */
export function getStoryboard(id: string): Promise<Storyboard[]> {
  return request.get(`/projects/${id}/storyboard`)
}

/**
 * 更新单个分镜镜头
 * @param id - 项目 ID
 * @param seq - 镜头序号
 * @param data - 更新参数（对齐后端 StoryboardUpdateRequest）
 * @returns 更新后的分镜信息
 */
export function updateStoryboard(
  id: string,
  seq: number,
  data: StoryboardUpdateParams,
): Promise<Storyboard> {
  return request.put(`/projects/${id}/storyboard/${seq}`, data)
}

/**
 * 按分镜 ID 顺序重排分镜（拖拽排序 SB-04）
 * @param id - 项目 ID
 * @param orderedIds - 按新顺序排列的分镜 ID 列表（完整覆盖项目全部分镜）
 * @returns 重排后的分镜列表
 */
export function reorderStoryboard(id: string, orderedIds: number[]): Promise<Storyboard[]> {
  return request.put(`/projects/${id}/storyboard/reorder`, { ordered_ids: orderedIds })
}

/** 连续性问题项（SB-06） */
export interface ContinuityIssue {
  /** 出现衔接问题的相邻两个分镜的镜头序号 */
  between: number[]
  /** 问题类型：角色 / 场景 / 时间 / 道具 */
  type: string
  /** 问题描述 */
  message: string
  /** 严重程度 */
  severity: 'low' | 'medium' | 'high'
}

/** 连续性检查结果（SB-06） */
export interface ContinuityCheckResult {
  /** LLM 检查是否成功完成 */
  checked: boolean
  /** 衔接问题列表 */
  issues: ContinuityIssue[]
}

/**
 * 调用 LLM 检查相邻分镜衔接问题（SB-06）
 * @param id - 项目 ID
 * @returns 检查结果（checked=false 表示 LLM 未能完成检查）
 */
export function checkContinuity(id: string): Promise<ContinuityCheckResult> {
  return request.post(`/projects/${id}/storyboard/continuity-check`)
}
