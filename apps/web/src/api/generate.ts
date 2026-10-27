/**
 * 生成阶段相关 API（关键帧、视频、配音）
 * 提供生成关键帧、生成视频、生成配音接口
 * @file api/generate.ts
 */

import request from './request'
import type { Task } from '@/types'

/** 生成关键帧请求参数 */
export interface GenerateKeyframesParams {
  /** 需要生成的镜头序号列表，为空则全部生成 */
  shots?: number[]
  /** 风格描述 */
  style?: string
}

/** 生成视频请求参数 */
export interface GenerateVideosParams {
  /** 需要生成的镜头序号列表 */
  shots?: number[]
  /** 视频分辨率 */
  resolution?: string
  /** 单镜头时长（秒） */
  duration?: number
}

/** 生成配音请求参数 */
export interface GenerateVoicesParams {
  /** 需要生成的镜头序号列表 */
  shots?: number[]
  /** 音色 ID */
  voice_id?: string
  /** 语速 */
  speed?: number
}

/** 音色库条目（GET /tts/voices 返回） */
export interface TtsVoice {
  /** 音色 ID */
  voice_id: string
  /** 音色名称 */
  name: string
  /** 性别：male / female / neutral */
  gender: string
  /** 风格描述 */
  style: string
  /** 所属 Provider：agnes / mock */
  provider: string
}

/** 字幕分段（GET /projects/{id}/subtitles 返回） */
export interface SubtitleSegment {
  /** 镜头序号 */
  sequence: number
  /** 字幕文本（台词） */
  text: string
  /** 起始时间（秒） */
  start: number
  /** 持续时间（秒） */
  duration: number
}

/** 项目字幕查询结果 */
export interface ProjectSubtitles {
  /** 拼装完成的全片 SRT 字幕文本 */
  srt: string
  /** 分镜级字幕分段列表 */
  segments: SubtitleSegment[]
  /** 字幕分段总数 */
  total: number
}

/**
 * 查询内置音色库（VO-02）
 * @returns 音色列表 [{voice_id, name, gender, style, provider}]
 */
export function getTtsVoices(): Promise<TtsVoice[]> {
  return request.get('/tts/voices')
}

/** 音色试听结果 */
export interface TtsPreviewResult {
  /** 合成音频 URL */
  url: string
  /** 音色 ID */
  voice_id: string
  /** 是否降级为占位音 */
  degraded?: boolean
}

/**
 * 试听指定音色（真实调用 TTS 合成试听文本）
 * @param voiceId - 音色 ID
 * @param text - 试听文本
 * @returns 音频 URL
 */
export function previewVoice(voiceId: string, text?: string): Promise<TtsPreviewResult> {
  return request.post('/tts/preview', null, {
    params: { voice_id: voiceId, text: text || '你好，我是配音演员，这是我的试听效果。' },
  })
}

/**
 * 查询项目字幕（VO-05）
 * @param id - 项目 ID
 * @returns 全片 SRT 文本与分镜级字幕分段
 */
export function getSubtitles(id: string): Promise<ProjectSubtitles> {
  return request.get(`/projects/${id}/subtitles`)
}

/**
 * 生成关键帧
 * @param id - 项目 ID
 * @param data - 生成参数
 * @returns 后台任务信息
 */
export function generateKeyframes(id: string, data: GenerateKeyframesParams): Promise<Task> {
  return request.post(`/projects/${id}/generate/keyframes`, data)
}

/**
 * 生成视频
 * @param id - 项目 ID
 * @param data - 生成参数
 * @returns 后台任务信息
 */
export function generateVideos(id: string, data: GenerateVideosParams): Promise<Task> {
  return request.post(`/projects/${id}/generate/videos`, data)
}

/**
 * 生成配音
 * @param id - 项目 ID
 * @param data - 生成参数
 * @returns 后台任务信息
 */
export function generateVoices(id: string, data: GenerateVoicesParams): Promise<Task> {
  return request.post(`/projects/${id}/generate/voices`, data)
}

/** 单句配音：生成 TTS 并写回分镜 */
export function saveVoiceLine(id: string, sbId: number, voiceId: string, text: string, speed?: number): Promise<{ url: string }> {
  return request.post(`/projects/${id}/storyboards/${sbId}/voice`, { voice_id: voiceId, text, speed: speed ?? 1.0 })
}

/** 绑定角色音色（持久化） */
export function saveVoiceBind(id: string, cid: number, voiceId: string): Promise<{ cid: number; voice_id: string }> {
  return request.put(`/projects/${id}/characters/${cid}/voice`, { voice_id: voiceId })
}

/** 保存用户勾选的字幕文本列表 */
export function saveSubtitleSelection(id: string, texts: string[]): Promise<{ saved: number }> {
  return request.post(`/projects/${id}/subtitles/save`, { selected_texts: texts })
}

/** 读取用户字幕勾选 */
export function loadSubtitleSelection(id: string): Promise<{ selected_texts: string[] }> {
  return request.get(`/projects/${id}/subtitles/selection`)
}

/** 视频重新生成请求参数（VID-07 降级换模） */
export interface RegenerateVideoParams {
  /**
   * 指定视频 Provider：minimax / zhipu / agnes / mock（降级占位生成），
   * 缺省用系统默认（对齐后端 VideoProviderRegistry 注册的 provider 名称）
   */
  provider?: 'minimax' | 'zhipu' | 'agnes' | 'mock'
}

/** 视频重新生成响应 */
export interface RegenerateVideoResult {
  /** 新创建的视频生成任务 ID */
  new_task_id: number
  /** 本次指定的 Provider 名称（为空表示系统默认） */
  provider?: 'minimax' | 'zhipu' | 'agnes' | 'mock' | null
}

/**
 * 视频任务换模重新生成（VID-07）：标记原任务废弃并创建新任务
 * @param id - 项目 ID
 * @param taskId - 原视频任务 ID
 * @param data - 重生成参数（可选 provider）
 * @returns 新任务 ID 与 provider
 */
export function regenerateVideo(
  id: string,
  taskId: string,
  data?: RegenerateVideoParams,
): Promise<RegenerateVideoResult> {
  return request.post(`/projects/${id}/video/${taskId}/regenerate`, data ?? {})
}
