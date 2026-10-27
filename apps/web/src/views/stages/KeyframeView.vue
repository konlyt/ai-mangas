<!--
  P08 关键帧工作台
  功能：
    1. 分镜缩略图墙：关键帧图 + 状态徽标 + 相似度分数
    2. 生成范围选择器：单张 / 选中批量 / 全量
    3. 单镜详情抽屉：大图预览、提示词编辑、首尾帧模式开关
    4. 顶部批量进度条 + 进入视频生成按钮
    5. hover 缩略图放大预览
  @file views/stages/KeyframeView.vue
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { StoryboardShot, ConsistencyReportItem, ConsistencyCheckMode } from '@/types'
import { generateKeyframes } from '@/api/generate'
import { getStoryboard } from '@/api/storyboard'
import { getConsistency } from '@/api/assets'
import { getGraphState } from '@/api/graph'
import StageStepper from '@/components/StageStepper.vue'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.id as string)

/** 加载状态 */
const loading = ref(false)
/** 分镜列表 */
const shots = ref<StoryboardShot[]>([])
/** 一致性校验报告列表（优先 graph state 原始数据，兜底 DB 落库数据） */
const consistencyReports = ref<ConsistencyReportItem[]>([])
/** 选中的镜头序号集合 */
const selectedSeqs = ref<Set<number>>(new Set())
/** 生成中状态 */
const generating = ref(false)
/** 生成进度 */
const generateProgress = ref(0)

/** 生成范围 */
const generateScope = ref<'single' | 'batch' | 'all'>('all')

/** 详情抽屉 */
const drawerVisible = ref(false)
const currentShot = ref<StoryboardShot | null>(null)
/** 首尾帧模式 */
const frameMode = ref<'single' | 'first-last'>('single')
/** 编辑的提示词 */
const editPrompt = ref('')

/**
 * 镜头状态映射
 * @param seq - 镜头序号
 * @returns 状态文本与类型
 */
function shotStatus(seq: number): { text: string; type: 'success' | 'warning' | 'info' } {
  const shot = shots.value.find((s) => s.seq === seq)
  if (shot?.image_url) return { text: '已完成', type: 'success' }
  if (generating.value) return { text: '生成中', type: 'warning' }
  return { text: '待生成', type: 'info' }
}

/**
 * 获取分镜列表，并同步拉取参考注入标记与一致性校验报告
 * 参考注入标记（ref_character_names/ref_count/ref_dropped）仅存在于
 * graph state（LangGraph checkpointer），DB 分镜表无对应列；
 * 一致性报告优先取 graph state 原始数据（含 check_mode/subject_name），
 * 兜底走 DB 落库数据（check_mode 由后端启发式推断补充）
 */
async function fetchShots(): Promise<void> {
  loading.value = true
  try {
    const data = (await getStoryboard(projectId.value)) as unknown as any
    const rawList: any[] = Array.isArray(data) ? data : (data?.shots ?? [])
    // 拉取 graph state（失败不阻塞分镜展示，标记与报告留空）
    let gsState: any = null
    try {
      const gs = (await getGraphState(projectId.value)) as unknown as any
      gsState = gs?.state ?? null
    } catch {
      gsState = null
    }
    // graph state 中按镜头序号索引的分镜标记
    const sbMarks = new Map<number, any>()
    for (const sb of gsState?.storyboards ?? []) {
      if (sb && typeof sb === 'object') sbMarks.set(Number(sb.sequence), sb)
    }
    shots.value = rawList.map((s: any, i: number) => {
      const seq = Number(s?.seq ?? s?.sequence ?? i + 1)
      const mark = sbMarks.get(seq) ?? {}
      return {
        id: Number(s?.id) || undefined,
        seq,
        description: s?.description ?? s?.visual_description ?? '',
        shot_type: s?.shot_type,
        camera_movement: s?.camera_movement,
        duration: Number(s?.duration) || 5,
        image_url: s?.image_url ?? s?.keyframe_url,
        keyframe_url: s?.keyframe_url,
        status: s?.status,
        ref_character_names: Array.isArray(mark.ref_character_names)
          ? mark.ref_character_names
          : [],
        ref_count: Number(mark.ref_count) || 0,
        ref_dropped: Boolean(mark.ref_dropped),
      }
    })
    // 一致性报告：graph state 优先（原始 check_mode），DB 兜底
    const stateReports: ConsistencyReportItem[] = gsState?.consistency?.reports ?? []
    if (stateReports.length > 0) {
      consistencyReports.value = stateReports
    } else {
      try {
        consistencyReports.value = await getConsistency(projectId.value)
      } catch {
        consistencyReports.value = []
      }
    }
  } catch (e) {
    ElMessage.error('获取分镜列表失败')
  } finally {
    loading.value = false
  }
}

/**
 * 一致性报告的校验模式标注推断
 * 优先使用报告自带的 check_mode（graph state 原始值 / 后端推断值）；
 * 仍缺省时按 action 与得分在前端做同样的启发式推断：
 * manual+有得分 → ref_lock（参考锁定低分仅记录不自动重生成，唯一组合）；
 * regenerate → feature_card；无得分且 pass → quality_gate；其余 → feature_card
 * @param r - 一致性报告项
 * @returns tag 文本与类型（ref_lock 绿色"参考锁定"，quality_gate 灰色"基础质检"，默认灰色"特征卡"）
 */
function modeTag(r: ConsistencyReportItem): { text: string; type: 'success' | 'info' } {
  const cm: ConsistencyCheckMode =
    r.check_mode ??
    (r.action === 'manual' && r.similarity_score != null
      ? 'ref_lock'
      : r.action === 'regenerate'
        ? 'feature_card'
        : r.similarity_score == null && r.action === 'pass'
          ? 'quality_gate'
          : 'feature_card')
  if (cm === 'ref_lock') return { text: '参考锁定', type: 'success' }
  if (cm === 'quality_gate') return { text: '基础质检', type: 'info' }
  return { text: '特征卡', type: 'info' }
}

/**
 * 处置动作中文文案
 * @param action - 处置动作（pass / regenerate / manual）
 * @returns 中文文案
 */
function actionText(action: string): string {
  if (action === 'pass') return '通过'
  if (action === 'regenerate') return '待重生成'
  return '人工关注'
}

/**
 * 获取指定镜头关键帧的真实一致性得分
 * 按 subject_name 匹配 "分镜#N" 或多角色逐角色报告 "分镜#N·角色名"
 * （正则锚定序号边界，避免 分镜#1 误匹配 分镜#10）
 * @param seq - 镜头序号
 * @returns 得分百分比整数；无带得分的报告时返回 null
 */
function scoreForShot(seq: number): number | null {
  const re = new RegExp(`^分镜#${seq}(·|$)`)
  const hit = consistencyReports.value.find(
    (r) =>
      r.subject_type === 'keyframe' &&
      !!r.subject_name &&
      re.test(r.subject_name) &&
      r.similarity_score != null
  )
  return hit?.similarity_score != null ? Math.round(hit.similarity_score * 100) : null
}

/**
 * 构造 {{ref N}} 参考图协议占位符文本
 * （与后端 keyframe_agent 提示词注入的 {{ref N}} 协议一致，N 从 1 递增；
 * 因 Vue 模板中大括号是插值定界符，需由函数返回字面量）
 * @param idx - 参考图序号（从 0 起）
 * @returns 形如 "{{ref 1}}" 的占位符文本
 */
function refTag(idx: number): string {
  return `{{ref ${idx + 1}}}`
}

/**
 * 切换镜头选中状态
 * @param seq - 镜头序号
 */
function toggleSelect(seq: number): void {
  if (selectedSeqs.value.has(seq)) {
    selectedSeqs.value.delete(seq)
  } else {
    selectedSeqs.value.add(seq)
  }
  selectedSeqs.value = new Set(selectedSeqs.value)
}

/**
 * 全选/取消全选
 */
function toggleSelectAll(): void {
  if (selectedSeqs.value.size === shots.value.length) {
    selectedSeqs.value = new Set()
  } else {
    selectedSeqs.value = new Set(shots.value.map((s) => s.seq))
  }
}

/**
 * 获取要生成的镜头序号列表
 */
function getTargetSeqs(): number[] {
  if (generateScope.value === 'all') return shots.value.map((s) => s.seq)
  if (generateScope.value === 'batch') return Array.from(selectedSeqs.value)
  return []
}

/**
 * 生成关键帧
 */
async function handleGenerate(): Promise<void> {
  const seqs = getTargetSeqs()
  if (seqs.length === 0 && generateScope.value !== 'all') {
    ElMessage.warning('请先选择要生成的镜头')
    return
  }
  generating.value = true
  generateProgress.value = 0
  try {
    await generateKeyframes(projectId.value, { shots: seqs })
    // 模拟进度
    const timer = setInterval(() => {
      generateProgress.value += 8
      if (generateProgress.value >= 100) {
        clearInterval(timer)
        generating.value = false
        fetchShots()
        ElMessage.success('关键帧生成完成')
      }
    }, 400)
  } catch (e) {
    generating.value = false
    ElMessage.error('关键帧生成失败')
  }
}

/**
 * 打开镜头详情抽屉
 * @param shot - 镜头对象
 */
function openDetail(shot: StoryboardShot): void {
  currentShot.value = shot
  editPrompt.value = (shot as any).prompt || shot.description || ''
  drawerVisible.value = true
}

/**
 * 保存提示词
 */
function handleSavePrompt(): void {
  if (currentShot.value) {
    ;(currentShot.value as any).prompt = editPrompt.value
    ElMessage.success('提示词已保存')
  }
}

/**
 * 重新生成单个镜头的关键帧
 */
async function handleRegenerateSingle(): Promise<void> {
  if (!currentShot.value || !currentShot.value.id) {
    ElMessage.warning('镜头数据缺少 ID，无法重新生成')
    return
  }
  generating.value = true
  try {
    await generateKeyframes(projectId.value, {
      storyboard_ids: [currentShot.value.id],
      mode: 'all',
    } as any)
    ElMessage.success(`正在重新生成镜头 #${currentShot.value.seq}，请稍后刷新查看`)
    setTimeout(() => {
      fetchShots()
      generating.value = false
    }, 3000)
  } catch (e) {
    generating.value = false
    ElMessage.error('重新生成失败')
  }
}

/**
 * 进入视频生成阶段
 */
function goVideoStage(): void {
  router.push(`/project/${projectId.value}/video`)
}

onMounted(() => {
  fetchShots()
})
</script>

<template>
  <div class="keyframe-view" v-loading="loading">
    <div class="page-header">
      <div class="page-title-group">
        <el-button text @click="$router.push(`/project/${projectId}/storyboard`)" class="nav-arrow">
          <el-icon><ArrowLeft /></el-icon> 分镜设计
        </el-button>
        <h1 class="page-title">关键帧工作台</h1>
        <el-button text type="primary" @click="goVideoStage" class="nav-arrow">
          视频生成 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
      <el-button type="primary" size="large" @click="goVideoStage">
        进入视频生成
        <el-icon class="el-icon--right"><ArrowRight /></el-icon>
      </el-button>
    </div>
    <StageStepper current-stage="generate" />

    <!-- 批量进度条 -->
    <el-progress
      v-if="generating"
      :percentage="generateProgress"
      :stroke-width="10"
      status="success"
      style="margin-bottom: 16px"
    />

    <!-- 生成范围选择与操作 -->
    <div class="scope-bar">
      <span class="scope-label">生成范围：</span>
      <el-radio-group v-model="generateScope" size="default">
        <el-radio-button label="single">单张</el-radio-button>
        <el-radio-button label="batch">选中批量</el-radio-button>
        <el-radio-button label="all">全量</el-radio-button>
      </el-radio-group>
      <el-button v-if="generateScope === 'batch'" @click="toggleSelectAll">
        {{ selectedSeqs.size === shots.length && shots.length > 0 ? '取消全选' : '全选' }}
      </el-button>
      <el-button
        type="primary"
        :loading="generating"
        @click="handleGenerate"
      >
        <el-icon><MagicStick /></el-icon>
        生成关键帧
      </el-button>
      <span class="selected-count" v-if="generateScope === 'batch'">
        已选 {{ selectedSeqs.size }} / {{ shots.length }}
      </span>
    </div>

    <!-- 缩略图墙 -->
    <el-empty v-if="shots.length === 0 && !loading" description="暂无分镜数据" />
    <div v-else class="thumb-wall">
      <div
        v-for="shot in shots"
        :key="shot.seq"
        class="thumb-card"
        :class="{ selected: selectedSeqs.has(shot.seq) }"
        @click="generateScope === 'batch' ? toggleSelect(shot.seq) : openDetail(shot)"
      >
        <el-tooltip placement="top" effect="dark" :show-after="300">
          <template #content>
            <div class="tooltip-preview">
              <el-image
                v-if="shot.image_url"
                :src="shot.image_url"
                fit="contain"
                style="width: 200px; height: 120px"
              />
              <div v-else style="color:#fff;padding:20px">暂无预览</div>
            </div>
          </template>
          <div class="thumb-image">
            <el-image v-if="shot.image_url" :src="shot.image_url" fit="cover" class="img" />
            <div v-else class="img-placeholder">
              <el-icon :size="32"><Picture /></el-icon>
            </div>
            <span class="seq-badge">#{{ shot.seq }}</span>
          </div>
        </el-tooltip>
        <div class="thumb-info">
          <el-tag :type="shotStatus(shot.seq).type" size="small">
            {{ shotStatus(shot.seq).text }}
          </el-tag>
          <!-- 真实一致性得分：从一致性报告按分镜匹配；无报告时不显示 -->
          <el-tag
            v-if="scoreForShot(shot.seq) !== null"
            type="warning"
            size="small"
            class="similarity"
          >
            相似度 {{ scoreForShot(shot.seq) }}%
          </el-tag>
        </div>
        <!-- 参考注入 chips：{{ref N}} ↔ 角色名 对应关系（与生成提示词的 {{ref N}} 协议一致） -->
        <div v-if="shot.ref_character_names?.length" class="ref-chips">
          <el-tag
            v-for="(name, idx) in shot.ref_character_names.slice(0, 3)"
            :key="name + idx"
            :type="shot.ref_dropped ? 'danger' : 'success'"
            size="small"
            effect="plain"
          >
            {{ refTag(idx) }}↔{{ name }}
          </el-tag>
          <el-tag v-if="shot.ref_dropped" type="danger" size="small" effect="plain">
            参考图已降级丢弃
          </el-tag>
        </div>
      </div>
    </div>

    <!-- 一致性校验报告（参考注入与引用关系展示）：模式标注 + 得分 + 处置动作 -->
    <div v-if="consistencyReports.length" class="consistency-panel">
      <div class="panel-title">一致性校验报告</div>
      <div class="report-list">
        <div v-for="(r, i) in consistencyReports" :key="i" class="report-item">
          <el-tag :type="modeTag(r).type" size="small">{{ modeTag(r).text }}</el-tag>
          <span class="report-subject">
            {{ r.subject_name || (r.subject_type === 'keyframe' ? '分镜质检' : '角色资产') }}
          </span>
          <!-- 多角色逐角色报告（subject_name 形如 "分镜#N·角色名"）标注 -->
          <el-tag v-if="r.subject_name?.includes('·')" size="small" effect="plain" type="success">
            逐角色
          </el-tag>
          <span class="report-score">
            {{ r.similarity_score != null ? `得分 ${(r.similarity_score * 100).toFixed(0)}%` : '未比对' }}
          </span>
          <span class="report-action">{{ actionText(r.action) }}</span>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="currentShot ? `镜头 #${currentShot.seq}` : '关键帧详情'"
      direction="rtl"
      size="480px"
    >
      <div v-if="currentShot" class="detail-content">
        <el-image
          v-if="currentShot.image_url"
          :src="currentShot.image_url"
          fit="contain"
          class="detail-image"
        />
        <div v-else class="detail-placeholder">
          <el-icon :size="60"><Picture /></el-icon>
          <p>暂无关键帧</p>
        </div>

        <el-divider content-position="left">帧模式</el-divider>
        <el-radio-group v-model="frameMode">
          <el-radio-button label="single">单帧</el-radio-button>
          <el-radio-button label="first-last">首尾帧</el-radio-button>
        </el-radio-group>

        <el-divider content-position="left">绘图提示词</el-divider>
        <el-input v-model="editPrompt" type="textarea" :rows="5" placeholder="编辑提示词..." />
        <div style="margin-top: 12px; display: flex; gap: 8px;">
          <el-button type="primary" @click="handleSavePrompt">
            保存提示词
          </el-button>
          <el-button type="warning" :loading="generating" @click="handleRegenerateSingle">
            <el-icon><MagicStick /></el-icon>
            重新生成此镜头
          </el-button>
        </div>

        <el-divider content-position="left">镜头信息</el-divider>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="景别">{{ currentShot.shot_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="运镜">{{ currentShot.camera_move || '-' }}</el-descriptions-item>
          <el-descriptions-item label="对白">{{ currentShot.dialogue || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.keyframe-view {
  min-height: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-arrow {
  font-size: 14px;
}

.page-title {
  font-size: 22px;
  margin: 0;
}

.scope-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.scope-label {
  font-size: 14px;
  color: var(--ai-text-regular);
}

.selected-count {
  font-size: 13px;
  color: var(--ai-primary-color);
}

.thumb-wall {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
}

.thumb-card {
  border: 2px solid transparent;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  background: #fff;
  transition: border-color 0.2s;

  &:hover {
    border-color: var(--ai-primary-light);
  }

  &.selected {
    border-color: var(--ai-primary-color);
  }
}

.thumb-image {
  position: relative;
  height: 120px;
  background: var(--ai-bg-color);
}

.img {
  width: 100%;
  height: 100%;
}

.img-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ai-text-placeholder);
}

.seq-badge {
  position: absolute;
  top: 4px;
  left: 6px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
}

.thumb-info {
  display: flex;
  justify-content: space-between;
  padding: 8px;
  align-items: center;
}

.similarity {
  font-size: 11px;
}

/* 参考注入 chips（{{ref N}} ↔ 角色名） */
.ref-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 0 8px 8px;
}

/* 一致性校验报告面板 */
.consistency-panel {
  margin-top: 20px;
  padding: 12px 16px;
  background: var(--ai-bg-color);
  border-radius: 8px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.report-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.report-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.report-subject {
  color: var(--ai-text-regular);
}

.report-score,
.report-action {
  color: var(--ai-text-secondary);
}

.report-score {
  margin-left: auto;
}

.report-action {
  min-width: 56px;
  text-align: right;
}

.detail-content {
  padding: 8px;
}

.detail-image {
  width: 100%;
  height: 280px;
  border-radius: 8px;
  overflow: hidden;
}

.detail-placeholder {
  width: 100%;
  height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ai-text-placeholder);
  background: var(--ai-bg-color);
  border-radius: 8px;
  gap: 10px;
}
</style>
