/**
 * 历史版本相关 API
 * 提供版本列表、恢复版本接口
 * @file api/revisions.ts
 */

import request from './request'
import type { Revision } from '@/types'

/**
 * 获取项目历史版本列表
 * @param id - 项目 ID
 * @returns 版本列表
 */
export function listRevisions(id: string): Promise<Revision[]> {
  return request.get(`/projects/${id}/revisions`)
}

/**
 * 恢复到指定历史版本
 * @param id - 项目 ID
 * @param rid - 版本 ID
 * @returns 恢复结果
 */
export function restoreRevision(id: string, rid: string): Promise<void> {
  return request.post(`/projects/${id}/revisions/${rid}/restore`)
}
