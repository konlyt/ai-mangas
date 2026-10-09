/**
 * 模型相关 API
 * 提供模型列表、设置项目模型、校验 API Key 等接口
 * @file api/models.ts
 */

import request from './request'
import type { Model } from '@/types'

/** 模型列表查询参数 */
export interface ModelListParams {
  /** 按模型类型过滤 */
  type?: Model['type']
  /** 按供应商过滤 */
  provider?: string
  /** 项目 ID（用于标记当前项目默认模型） */
  project_id?: string
}

/** 设置项目模型请求参数 */
export interface SetProjectModelParams {
  /** 模型类型 */
  type: Model['type']
  /** 模型 ID */
  model_id: string
}

/** 校验 API Key 请求参数 */
export interface VerifyKeyParams {
  /** 供应商名称 */
  provider: string
  /** API Key */
  api_key: string
}

/**
 * 获取可用模型列表
 * @param params - 查询参数
 * @returns 模型列表
 */
export function listModels(params?: ModelListParams): Promise<Model[]> {
  return request.get('/models', { params })
}

/**
 * 设置项目使用的模型
 * @param id - 项目 ID
 * @param data - 模型设置参数
 * @returns 设置结果
 */
export function setProjectModel(id: string, data: SetProjectModelParams): Promise<void> {
  return request.post(`/projects/${id}/models`, data)
}

/**
 * 校验供应商 API Key 是否有效
 * @param data - 校验参数
 * @returns 校验结果（success 字段）
 */
export function verifyKey(data: VerifyKeyParams): Promise<{ success: boolean; message?: string }> {
  return request.post('/models/verify-key', data)
}
