/**
 * 资产相关 API（角色、场景）
 * 提供生成角色、获取角色、锁定角色、获取场景等接口
 * @file api/assets.ts
 */

import request from './request'
import type { Character, CharacterLocks, Scene, ConsistencyReportItem } from '@/types'

/** 含参考图的角色信息（在 Character 基础上扩展后端 reference_url 字段） */
export interface CharacterWithReference extends Character {
  /** 用户上传的参考图 URL */
  reference_url?: string
}

/** 参考图上传接口返回结果 */
export interface ReferenceUploadResult {
  /** 参考图访问 URL（/static/references/...） */
  url: string
  /** 落盘文件名 */
  filename: string
}

/**
 * 根据剧本生成角色
 * @param id - 项目 ID
 * @returns 生成的角色列表
 */
export function generateCharacters(id: string): Promise<Character[]> {
  return request.post(`/projects/${id}/assets/characters`, {}, { timeout: 300000 })
}

/**
 * 获取项目角色列表（含参考图 URL）
 * @param id - 项目 ID
 * @returns 角色列表
 */
export function getCharacters(id: string): Promise<CharacterWithReference[]> {
  return request.get(`/projects/${id}/assets/characters`)
}

/**
 * 锁定指定角色（锁定后不可再重新生成）
 * @param id - 项目 ID
 * @param cid - 角色 ID
 * @returns 更新后的角色信息
 */
export function lockCharacter(id: string, cid: string): Promise<Character> {
  return request.post(`/projects/${id}/assets/characters/${cid}/lock`)
}

/**
 * 解锁角色，允许重新生成
 * @param id - 项目 ID
 * @param cid - 角色 ID
 * @returns 更新后的角色信息
 */
export function unlockCharacter(id: string, cid: string): Promise<Character> {
  return request.post(`/projects/${id}/assets/characters/${cid}/unlock`)
}

/**
 * 删除角色
 * @param id - 项目 ID
 * @param cid - 角色 ID
 */
export function deleteCharacter(id: string, cid: string): Promise<void> {
  return request.delete(`/projects/${id}/assets/characters/${cid}`)
}

/**
 * 重新生成单个角色（换一张）
 * @param id - 项目 ID
 * @param cid - 角色 ID
 * @param visualPrompt - 可选的新视觉提示词
 * @returns 更新后的角色信息
 */
export function regenerateCharacter(
  id: string,
  cid: string,
  visualPrompt?: string
): Promise<Character> {
  return request.post(
    `/projects/${id}/assets/characters/${cid}/regenerate`,
    { visual_prompt: visualPrompt },
    { timeout: 300000 }
  )
}

/**
 * 上传角色参考图（multipart，jpg/png/webp，≤5MB）
 * @param projectId - 项目 ID
 * @param assetId - 角色 ID
 * @param file - 图片文件对象
 * @returns 上传结果（含访问 URL 与落盘文件名）
 */
export function uploadReference(
  projectId: string,
  assetId: string,
  file: File
): Promise<ReferenceUploadResult> {
  const formData = new FormData()
  formData.append('file', file)
  // FormData 由 axios 自动设置 multipart Content-Type（含 boundary），不要手动指定
  return request.post(`/projects/${projectId}/assets/${assetId}/reference`, formData)
}

/**
 * 更新角色一致性锚点（整体替换语义：空串/未提供的键被清空）
 * @param projectId - 项目 ID
 * @param characterId - 角色 ID
 * @param locks - 四项锚点（costume/hairstyle/appearance/body_type，空串=清空对应项）
 * @returns 更新后的锚点字典
 */
export function updateCharacterLocks(
  projectId: string,
  characterId: string,
  locks: CharacterLocks
): Promise<CharacterLocks> {
  return request.put(`/projects/${projectId}/assets/characters/${characterId}/locks`, locks)
}

/**
 * 获取项目场景列表
 * @param id - 项目 ID
 * @returns 场景列表
 */
export function getScenes(id: string): Promise<Scene[]> {
  return request.get(`/projects/${id}/assets/scenes`)
}

/**
 * 查询项目一致性校验报告（DB 落库数据）
 * 说明：check_mode 已由后端 consistency_agent 真实落库
 * （ConsistencyReport.check_mode 列），组装时直接读列，
 * 列为 NULL 时回退 'quality_gate'
 * @param id - 项目 ID
 * @returns 一致性报告列表
 */
export function getConsistency(id: string): Promise<ConsistencyReportItem[]> {
  return request.get(`/projects/${id}/consistency`)
}
