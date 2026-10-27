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

/** 用户使用量统计（对齐后端 UsageOut） */
export interface UserUsage {
  /** 项目总数 */
  project_count: number
  /** 图片数量 */
  image_count: number
  /** 视频时长（秒） */
  video_duration: number
  /** 累计消耗点数 */
  cost_points: number
  /** 按日统计数组 */
  daily: DailyUsageItem[]
}

/** 单日用量明细（对齐后端 DailyUsage） */
export interface DailyUsageItem {
  /** 日期（YYYY-MM-DD） */
  date: string
  /** 当日消耗点数 */
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

/** 剧本分场（content 结构化 JSON 解析出的场次项） */
export interface ScriptScene {
  /** 场次序号 */
  seq: number
  /** 场次标题 */
  title: string
  /** 场次描述 */
  description: string
  /** 场次缩略图 URL（LLM 生成 content 时可能附带） */
  thumbnail?: string
  /** 场次梗概（LLM 生成 content 时可能附带） */
  summary?: string
}

/** 角色一致性锚点（对齐后端 character_locks JSON 列：不可变锚点四项） */
export interface CharacterLocks {
  /** 服饰锚点 */
  costume?: string
  /** 发型锚点 */
  hairstyle?: string
  /** 外貌锚点 */
  appearance?: string
  /** 体型锚点 */
  body_type?: string
}

/** 角色信息（对齐后端 CharacterOut） */
export interface Character {
  /** 角色 ID */
  id: string
  /** 角色名称 */
  name: string
  /** 角色描述 */
  description: string
  /** 角色参考图 URL */
  image_url?: string
  /** 主定妆照 URL（后端 main_asset_url） */
  main_asset_url?: string
  /** 四视图参考板 URL（头特写/正面/右侧90°/背面四宫格，未生成时为 null） */
  ref_board_url?: string | null
  /** 一致性不可变锚点（服饰/发型/外貌/体型，未生成时为 null） */
  character_locks?: CharacterLocks | null
  /** 是否锁定（后端 is_locked：0 未锁 / 非 0 已锁） */
  is_locked?: number
  /** 旧版锁定标记（后端不再返回，保留为可选以兼容存量代码的回退读取） */
  locked?: boolean
}

/** 场景信息（对齐后端 SceneOut） */
export interface Scene {
  /** 场景 ID */
  id: string
  /** 场景名称 */
  name: string
  /** 场景描述 */
  description: string
  /** 场景参考图 URL */
  image_url?: string
  /** 主视觉 URL（兼容字段：详情抽屉中与角色联合渲染；后端场景实际字段为 asset_url） */
  main_asset_url?: string
}

/** 分镜状态（对齐后端 StoryboardStatus 枚举） */
export type StoryboardStatus = 'pending' | 'generating' | 'done' | 'failed'

/** 分镜信息（对齐后端 StoryboardOut：单条分镜记录，列表接口返回 Storyboard[]） */
export interface Storyboard {
  /** 分镜 ID */
  id: number
  /** 项目 ID */
  project_id: number
  /** 剧本 ID */
  script_id: number
  /** 剧集 ID */
  episode_id?: number | null
  /** 镜头序号 */
  sequence: number
  /** 景别 */
  shot_type?: string | null
  /** 运镜方式 */
  camera_movement?: string | null
  /** 预计时长（秒） */
  duration: number
  /** 画面描述 */
  visual_description?: string | null
  /** 对白 / 旁白 */
  dialogue?: string | null
  /** 涉及角色 ID 列表 */
  character_ids?: number[] | null
  /** 场景 ID */
  scene_id?: number | null
  /** 绘图提示词 */
  prompt?: string | null
  /** 首帧 URL */
  keyframe_url?: string | null
  /** 尾帧 URL */
  endframe_url?: string | null
  /** 视频片段 URL */
  video_url?: string | null
  /** 配音 URL */
  audio_url?: string | null
  /** 状态 */
  status: StoryboardStatus
  /** 创建时间 */
  created_at: string
  /** 更新时间 */
  updated_at: string
}

/**
 * 分镜更新请求参数（对齐后端 StoryboardUpdateRequest）
 * 所有字段均可选，仅传入需要更新的字段
 */
export interface StoryboardUpdateParams {
  /** 景别 */
  shot_type?: string
  /** 运镜方式 */
  camera_movement?: string
  /** 预计时长（秒） */
  duration?: number
  /** 画面描述 */
  visual_description?: string
  /** 对白 / 旁白 */
  dialogue?: string
  /** 涉及角色 ID 列表 */
  character_ids?: number[]
  /** 场景 ID */
  scene_id?: number
  /** 绘图提示词 */
  prompt?: string
}

/**
 * @deprecated 旧版分镜镜头结构（{seq, description, camera_move...}）。
 * 后端实际返回 StoryboardOut（见 {@link Storyboard}），仅存量视图
 * （KeyframeView 等）仍以本地行形式使用，新代码请使用 Storyboard。
 */
export interface StoryboardShot {
  /** 分镜数据库 ID（后端 storyboard.id） */
  id?: number
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
  /** 生成时真实注入的参考角色名列表（graph state 分镜标记，DB 数据可能缺省） */
  ref_character_names?: string[]
  /** 注入的参考图数量（graph state 分镜标记） */
  ref_count?: number
  /** 参考图是否被 Provider 降级丢弃（i2i 失败回退纯 t2i） */
  ref_dropped?: boolean
}

/** 一致性校验模式（方案 A5/A6：ref_lock 参考锁定 / feature_card 特征卡 / quality_gate 基础质检） */
export type ConsistencyCheckMode = 'ref_lock' | 'feature_card' | 'quality_gate'

/** 一致性校验报告项（state.consistency.reports 与 DB 落库报告的并集结构） */
export interface ConsistencyReportItem {
  /** 校验对象类型：asset（角色资产）/ keyframe（分镜关键帧） */
  subject_type: string
  /** 校验对象名称：角色名 / "分镜#N" / 多角色逐角色报告 "分镜#N·角色名" */
  subject_name?: string | null
  /** 校验对象 ID（DB 数据提供；state 报告可能缺省） */
  subject_id?: number | null
  /** 综合相似度得分（0~1，无法比对时为 null） */
  similarity_score?: number | null
  /** 判定阈值 */
  threshold?: number
  /** 处置动作：pass 通过 / regenerate 待重生成 / manual 人工关注 */
  action: string
  /** 校验模式（state 数据直接携带；DB 兜底数据由后端启发式推断补充） */
  check_mode?: ConsistencyCheckMode | null
  /** 附加说明（如 ref_lock 低分不自动重生成的提示） */
  note?: string
  /** 失败原因（图像比对失败等） */
  error?: string
  /** 报告生成时间（DB 数据提供） */
  created_at?: string | null
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
