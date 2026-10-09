/**
 * 全局事件总线
 * 基于 mitt 实现跨组件事件通信，用于 HITL 待确认、模型切换等全局事件广播
 * @file utils/eventBus.ts
 */

import mitt from 'mitt'

/** 全局事件类型映射 */
export interface GlobalEvents {
  /** 打开任务中心抽屉 */
  'task-center:open': void
  /** 打开模型配置抽屉 */
  'model-drawer:open': void
  /** 推送一条待确认（HITL）事项 */
  'pending-confirm:push': PendingConfirmItem
  /** 移除一条待确认事项 */
  'pending-confirm:remove': string
  /** 版本回退完成，需要刷新阶段数据 */
  'revision:restored': string
  /** 索引签名，满足 mitt 的 Record<EventType, unknown> 约束（含 symbol） */
  [key: string]: unknown
  [key: symbol]: unknown
}

/** 待确认事项结构 */
export interface PendingConfirmItem {
  /** 唯一 ID（通常为 run_id） */
  id: string
  /** 关联项目 ID */
  project_id: string
  /** 项目名称 */
  project_name?: string
  /** 当前阶段标识 */
  stage: string
  /** Agent 产出预览摘要 */
  summary: string
  /** 创建时间 */
  created_at: string
}

/** 创建 mitt 事件总线实例 */
const emitter = mitt<GlobalEvents>()

export default emitter
