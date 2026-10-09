/**
 * 合成阶段相关 API
 * 提供全量合成、局部合成、获取输出结果接口
 * @file api/compose.ts
 */

import request from './request'

/** 合成请求参数 */
export interface ComposeParams {
  /** 输出分辨率 */
  resolution?: string
  /** 输出格式 */
  format?: 'mp4' | 'mov'
  /** 背景音乐 URL */
  bgm_url?: string
  /** 音量 */
  volume?: number
}

/** 合成输出结果 */
export interface ComposeOutput {
  /** 输出文件 URL */
  url: string
  /** 文件名 */
  filename: string
  /** 文件大小（字节） */
  size: number
  /** 时长（秒） */
  duration: number
}

/**
 * 全量合成最终视频
 * @param id - 项目 ID
 * @param data - 合成参数
 * @returns 包含后台任务 ID 的对象
 */
export function compose(id: string, data: ComposeParams): Promise<{ task_id: number }> {
  return request.post(`/projects/${id}/compose`, data)
}

/**
 * 局部合成（仅合成指定分镜，产出预览片）
 * @param id - 项目 ID
 * @param data - 局部合成参数（storyboard_ids 为分镜 ID 列表）
 * @returns 包含后台任务 ID 的对象
 */
export function partialCompose(id: string, data: { storyboard_ids: number[] }): Promise<{ task_id: number }> {
  return request.post(`/projects/${id}/compose/partial`, data)
}

/**
 * 获取项目最终输出结果
 * @param id - 项目 ID
 * @returns 合成输出结果
 */
export function getOutput(id: string): Promise<ComposeOutput> {
  return request.get(`/projects/${id}/output`)
}

/** 导出请求参数 */
export interface ExportParams {
  /** 导出比例：9:16 或 16:9，缺省使用项目配置 */
  ratio?: '9:16' | '16:9'
}

/** 导出结果 */
export interface ExportResult {
  /** 导出文件下载 URL */
  url: string
  /** 导出比例 */
  ratio: string
  /** 文件大小（字节） */
  size: number
}

/** 最近一次导出记录 */
export interface ExportRecord {
  /** 导出文件下载 URL（无记录时为 null） */
  url: string | null
  /** 导出比例 */
  ratio: string | null
  /** 导出时间 */
  created_at: string | null
}

/**
 * 导出成片（按比例居中裁剪 + 轻量转码，同步返回下载 URL）
 * @param id - 项目 ID
 * @param data - 导出参数
 * @returns 导出结果（含下载 URL）
 */
export function exportVideo(id: string, data: ExportParams): Promise<ExportResult> {
  return request.post(`/projects/${id}/export`, data)
}

/**
 * 查询最近一次导出记录
 * @param id - 项目 ID
 * @returns 导出记录（可能为空）
 */
export function getLatestExport(id: string): Promise<ExportRecord> {
  return request.get(`/projects/${id}/export/latest`)
}
