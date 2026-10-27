/**
 * 剧本质量评分组合式函数（SCR-07）
 * 封装质量评分面板的状态与请求逻辑：四维评分、建议列表、请求态
 * @file composables/useQualityScore.ts
 */

import { reactive, ref, type Ref, type ComputedRef } from 'vue'
import { scoreScript } from '@/api/script'

/** 质量评分面板状态（接口失败时各分数为 null，展示 "—"） */
export interface QualityScoreState {
  /** 综合总分（0-100），未获取时为 null */
  overall: number | null
  /** 冲突强度（0-100），未获取时为 null */
  conflict: number | null
  /** 人物弧光（0-100），未获取时为 null */
  character: number | null
  /** 节奏把控（0-100），未获取时为 null */
  pacing: number | null
  /** 爽点密度（0-100），未获取时为 null */
  hookDensity: number | null
  /** 改进建议列表 */
  suggestions: string[]
  /** 一句话评语 */
  summary: string
  /** 是否为兜底估算评分（LLM 输出解析失败时为 true） */
  estimated: boolean
}

/**
 * 剧本质量评分组合式函数
 * @param projectId - 项目 ID（响应式）
 * @returns 评分状态与操作方法
 */
export function useQualityScore(projectId: Ref<string> | ComputedRef<string>) {
  /** 质量评分面板展示数据 */
  const qualityScore = reactive<QualityScoreState>({
    overall: null,
    conflict: null,
    character: null,
    pacing: null,
    hookDensity: null,
    suggestions: [],
    summary: '',
    estimated: false,
  })

  /** 是否显示质量评分面板 */
  const showQualityPanel = ref(false)

  /** 评分请求进行中 */
  const scoring = ref(false)

  /**
   * 重置质量评分为空态（各项显示 "—"）
   */
  function resetQualityScore(): void {
    qualityScore.overall = null
    qualityScore.conflict = null
    qualityScore.character = null
    qualityScore.pacing = null
    qualityScore.hookDensity = null
    qualityScore.suggestions = []
    qualityScore.summary = ''
    qualityScore.estimated = false
  }

  /**
   * 调用后端真实评分接口获取质量评分（SCR-07）
   * 打开评分面板并请求 LLM 四维评分；接口失败时各项显示 "—" 而非随机数
   */
  async function computeQualityScore(): Promise<void> {
    showQualityPanel.value = true
    scoring.value = true
    try {
      const data = await scoreScript(projectId.value)
      qualityScore.overall = data.overall ?? null
      qualityScore.conflict = data.conflict ?? null
      qualityScore.character = data.character ?? null
      qualityScore.pacing = data.pacing ?? null
      qualityScore.hookDensity = data.hook_density ?? null
      qualityScore.suggestions = Array.isArray(data.suggestions) ? data.suggestions : []
      qualityScore.summary = data.summary || ''
      qualityScore.estimated = Boolean(data.estimated)
    } catch (e) {
      // 接口失败：清空为 "—" 占位，错误提示由请求拦截器统一弹出
      resetQualityScore()
    } finally {
      scoring.value = false
    }
  }

  return {
    qualityScore,
    showQualityPanel,
    scoring,
    resetQualityScore,
    computeQualityScore,
  }
}
