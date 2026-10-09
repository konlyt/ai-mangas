/**
 * 全局 TypeScript 类型定义
 * 定义 API 响应、用户、项目、任务、分镜、角色、场景、模型等通用类型
 * @file types/index.ts
 */

/**
 * 统一 API 响应结构
 * @typeParam T - 业务数据类型
 */
export interface ApiResponse<T = unknown> {
  /** 业务状态码，0 表示成功 */
  code: number
  /** 业务提示消息 */
  message: string
  /** 业务数据 */
  data: T
}

/** 分页响应结构 */
export interface PageResult<T = unknown> {
  /** 数据列表 */
  list: T[]
  /** 总条数 */
  total: number
  /** 当前页码 */
  page: number
  /** 每页条数 */
  page_size: number
  /** 总页数 */
  total_pages: number
}

/** 分页查询参数 */
export interface PageParams {
  /** 页码 */
  page?: number
  /** 每页条数 */
  page_size?: number
}

/** 用户信息 */
export interface User {
  /** 用户 ID */
  id: string
  /** 用户名 */
  username: string
  /** 昵称 */
  nickname?: string
  /** 邮箱 */
  email?: string
  /** 头像 URL */
  avatar?: string
  /** 创建时间 */
  created_at?: string
}

/** 用户配额信息 */
export interface UserQuota {
  /** 剩余点数 */
  quota: number
  /** 会员等级 */
  vip_level: number
}

/** 用户使用量统计 */
export interface UserUsage {
  /** 项目总数 */
  project_count: number
  /** 图片数量 */
  image_count: number
  /** 视频时长（秒） */
  video_duration: number
  /** 累计消耗点数 */
  cost_points: number
}

/** 项目信息 */
export interface Project {
  /** 项目 ID */
  id: number
  /** 用户 ID */
  user_id: number
  /** 项目标题 */
  title: string
  /** 体裁 */
  genre?: string
  /** 视觉风格 */
  style?: string
  /** 项目阶段 */
  status: string
  /** 输出比例 */
  aspect_ratio?: string
  /** 项目封面图 URL */
  cover_url?: string
  /** 创建时间 */
  created_at: string
  /** 更新时间 */
  updated_at: string
}

/** 创建项目请求参数 */
export interface CreateProjectParams {
  /** 项目标题 */
  title: string
  /** 体裁 */
  genre?: string
  /** 视觉风格 */
  style?: string
  /** 输出比例 */
  aspect_ratio?: string
  /** 原始输入文本 */
  raw_input?: string
}

/** 更新项目请求参数 */
export interface UpdateProjectParams {
  /** 项目标题 */
  title?: string
  /** 体裁 */
  genre?: string
  /** 封面 URL */
  cover_url?: string
}

/** 项目统计信息 */
export interface ProjectStats {
  /** 今日新建项目数 */
  today_projects: number
  /** 本月新建项目数 */
  month_projects: number
  /** 图片数量 */
  image_count: number
  /** 视频时长（秒） */
  video_duration: number
  /** 累计消耗点数 */
  cost_points: number
}

/** 任务状态枚举 */
export type TaskStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

/** 任务类型枚举 */
export type TaskType =
  | 'script'
  | 'character'
  | 'scene'
  | 'storyboard'
  | 'keyframes'
  | 'video'
  | 'voice'
  | 'compose'

/** 后台任务信息 */
export interface Task {
  /** 任务 ID */
  id: string
  /** 关联项目 ID */
  project_id: string
  /** 任务类型 */
  type: TaskType
  /** 任务状态 */
  status: TaskStatus
  /** 进度百分比 0-100 */
  progress: number
  /** 任务结果消息 */
  message?: string
  /** 创建时间 */
  created_at: string
  /** 更新时间 */
  updated_at: string
}

/** 剧本信息 */
export interface Script {
  /** 剧本 ID */
  id: string
  /** 项目 ID */
  project_id: string
  /** 剧本标题 */
  title: string
  /** 剧本正文内容（后端返回结构化 JSON，前端兼容字符串） */
  content: string | Record<string, unknown>
  /** 剧本大纲/分场 */
  scenes?: ScriptScene[]
  /** 更新时间 */
  updated_at: string
}

/** 剧本分场 */
export interface ScriptScene {
  /** 场次序号 */
  seq: number
  /** 场次标题 */
  title: string
  /** 场次描述 */
  description: string
}

/** 角色信息 */
export interface Character {
  /** 角色 ID */
  id: string
  /** 角色名称 */
  name: string
  /** 角色描述 */
  description: string
  /** 角色参考图 URL */
  image_url?: string
  /** 是否锁定（锁定后不可再生成） */
  locked: boolean
}

/** 场景信息 */
export interface Scene {
  /** 场景 ID */
  id: string
  /** 场景名称 */
  name: string
  /** 场景描述 */
  description: string
  /** 场景参考图 URL */
  image_url?: string
}

/** 分镜信息 */
export interface Storyboard {
  /** 分镜 ID */
  id: string
  /** 项目 ID */
  project_id: string
  /** 分镜列表 */
  shots: StoryboardShot[]
  /** 更新时间 */
  updated_at: string
}

/** 分镜单帧 */
export interface StoryboardShot {
  /** 镜头序号 */
  seq: number
  /** 镜头描述 */
  description: string
  /** 景别 */
  shot_type?: string
  /** 镜头运动 */
  camera_move?: string
  /** 台词 */
  dialogue?: string
  /** 旁白 */
  narration?: string
  /** 参考图 URL */
  image_url?: string
}

/** AI 模型信息 */
export interface Model {
  /** 模型 ID */
  id: string
  /** 模型名称 */
  name: string
  /** 模型类型（image/video/audio/llm） */
  type: 'image' | 'video' | 'audio' | 'llm'
  /** 模型供应商 */
  provider: string
  /** 是否为当前项目默认模型 */
  is_default?: boolean
  /** 该厂商是否已配置 API Key */
  key_configured?: boolean
}

/** 历史版本信息 */
export interface Revision {
  /** 版本 ID */
  id: string
  /** 关联项目 ID */
  project_id: string
  /** 版本类型 */
  type: string
  /** 版本快照数据 */
  snapshot: Record<string, unknown>
  /** 创建时间 */
  created_at: string
}
