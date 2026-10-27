<!--
  P07 分镜设计页
  功能：
    1. 三栏布局：左栏剧本原文、中栏分镜卡片网格、右栏编辑面板
    2. 分镜卡片：缩略图、镜头号、景别、运镜、时长、对白、状态
    3. 编辑面板：全字段编辑
    4. 底部全局时间轴 + 总时长统计
    5. 工具条：新增/删除/拆分/合并分镜、连续性检查
    6. 原生 HTML5 拖拽重排（乐观更新 + 失败回滚，SB-04）
    7. 节奏预览折叠面板（时长占比条形图，SB-05）
    8. 连续性检查结果弹窗 + 问题卡片高亮（SB-06）
  @file views/stages/StoryboardView.vue
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  reorderStoryboard,
  checkContinuity,
  type ContinuityCheckResult,
} from '@/api/storyboard'
import { useStoryboardRows } from '@/composables/useStoryboardRows'
import { useDragReorder } from '@/composables/useDragReorder'
import StageStepper from '@/components/StageStepper.vue'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.id as string)

/** 分镜行状态与增删改拆合逻辑（组合式函数封装） */
const {
  loading,
  rows,
  scriptContent,
  selectedSeq,
  targetDuration,
  editingShot,
  totalDuration,
  durationDiff,
  avgDuration,
  fetchStoryboard,
  handleGenerate,
  selectShot,
  handleSaveShot,
  handleAddShot,
  handleDeleteShot,
  handleSplitShot,
  handleMergeShot,
  rhythmWidth,
  isPeak,
} = useStoryboardRows(projectId)

/** 拖拽重排（SB-04，组合式函数封装，reorder 回调持久化到后端） */
const {
  dragIndex,
  dragOverIndex,
  reordering,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
} = useDragReorder(rows, {
  reorder: (ids) => reorderStoryboard(projectId.value, ids),
})

/** 景别选项 */
const shotTypeOptions = ['特写', '近景', '中景', '全景', '远景', '俯拍', '仰拍']
/** 运镜选项 */
const cameraMoveOptions = ['固定', '推', '拉', '摇', '移', '跟', '升降', '环绕']

/**
 * 确认分镜，进入生成阶段
 */
async function handleConfirm(): Promise<void> {
  try {
    await ElMessageBox.confirm('确认当前分镜设计？确认后将进入生成阶段。', '确认分镜', {
      type: 'warning',
    })
    ElMessage.success('分镜已确认，进入生成阶段')
    router.push(`/project/${projectId.value}/keyframes`)
  } catch (e) {
    // 用户取消
  }
}

/* ============ 连续性检查（SB-06） ============ */

/** 连续性检查弹窗可见性 */
const continuityVisible = ref(false)
/** 连续性检查请求中 */
const continuityLoading = ref(false)
/** 连续性检查结果 */
const continuityResult = ref<ContinuityCheckResult | null>(null)

/** 被问题波及的镜头序号集合（用于卡片高亮） */
const issueSeqSet = computed<Set<number>>(() => {
  const set = new Set<number>()
  continuityResult.value?.issues.forEach((it) => it.between.forEach((s) => set.add(s)))
  return set
})

/**
 * 执行连续性检查并弹出结果窗口
 */
async function handleContinuityCheck(): Promise<void> {
  if (rows.value.length < 2) {
    ElMessage.warning('至少需要两个分镜才能检查衔接')
    return
  }
  continuityLoading.value = true
  try {
    continuityResult.value = await checkContinuity(projectId.value)
    continuityVisible.value = true
  } catch (err) {
    // 请求失败已由拦截器统一提示
  } finally {
    continuityLoading.value = false
  }
}

/**
 * severity 映射为 Element Plus Tag 类型
 * @param severity - 严重程度（low/medium/high）
 * @returns Tag 类型名
 */
function severityTagType(severity: string): 'danger' | 'warning' | 'info' {
  if (severity === 'high') return 'danger'
  if (severity === 'medium') return 'warning'
  return 'info'
}

onMounted(() => {
  fetchStoryboard()
})
</script>

<template>
  <div class="storyboard-view" v-loading="loading">
    <div class="page-header">
      <h1 class="page-title">分镜设计</h1>
      <el-button v-if="rows.length === 0" type="primary" @click="handleGenerate">
        <el-icon><MagicStick /></el-icon>
        生成分镜
      </el-button>
    </div>
    <StageStepper current-stage="storyboard" />

    <!-- 工具条 -->
    <div class="toolbar">
      <el-button @click="handleAddShot">
        <el-icon><Plus /></el-icon>
        新增
      </el-button>
      <el-button :disabled="selectedSeq === null" @click="handleDeleteShot">
        <el-icon><Delete /></el-icon>
        删除
      </el-button>
      <el-button :disabled="selectedSeq === null" @click="handleSplitShot">
        <el-icon><Scissors /></el-icon>
        拆分
      </el-button>
      <el-button :disabled="selectedSeq === null" @click="handleMergeShot">
        <el-icon><Rank /></el-icon>
        合并
      </el-button>
      <el-button
        type="warning"
        plain
        :loading="continuityLoading"
        :disabled="rows.length < 2"
        @click="handleContinuityCheck"
      >
        <el-icon v-if="!continuityLoading"><View /></el-icon>
        连续性检查
      </el-button>
      <div class="toolbar-right">
        <span class="duration-label">目标时长：</span>
        <el-input-number v-model="targetDuration" :min="10" :max="600" size="small" />
        <span class="duration-unit">秒</span>
      </div>
    </div>

    <!-- 三栏布局 -->
    <div class="three-column">
      <!-- 左栏：剧本原文 -->
      <el-card class="col-left" shadow="never">
        <template #header><span>剧本原文</span></template>
        <div class="script-text">
          <el-empty v-if="!scriptContent" description="暂无剧本内容" :image-size="60" />
          <p v-else>{{ scriptContent }}</p>
        </div>
      </el-card>

      <!-- 中栏：分镜卡片网格 -->
      <el-card class="col-mid" shadow="never">
        <template #header>
          <span>分镜列表（共 {{ rows.length }} 镜，可拖拽排序）</span>
        </template>
        <el-empty v-if="rows.length === 0" description="暂无分镜" />
        <div v-else class="shot-grid">
          <div
            v-for="(shot, index) in rows"
            :key="shot.key"
            class="shot-card"
            :class="{
              selected: selectedSeq === shot.sequence,
              dragging: dragIndex === index,
              'drag-over': dragOverIndex === index && dragIndex !== null && dragIndex !== index,
              'has-issue': issueSeqSet.has(shot.sequence),
            }"
            draggable="true"
            @dragstart="onDragStart(index, $event)"
            @dragover="onDragOver(index, $event)"
            @drop="onDrop(index, $event)"
            @dragend="onDragEnd"
            @click="selectShot(shot)"
          >
            <div class="shot-thumb">
              <el-image v-if="shot.keyframe_url" :src="shot.keyframe_url" fit="cover" class="thumb-img" />
              <div v-else class="thumb-placeholder">
                <el-icon :size="28"><Picture /></el-icon>
              </div>
              <span class="shot-seq">#{{ shot.sequence }}</span>
              <span v-if="issueSeqSet.has(shot.sequence)" class="issue-badge" title="存在衔接问题">!</span>
            </div>
            <div class="shot-meta">
              <el-tag size="small" type="info">{{ shot.shot_type || '未设置' }}</el-tag>
              <el-tag size="small">{{ shot.camera_movement || '固定' }}</el-tag>
              <span class="shot-duration">{{ Number(shot.duration) || 3 }}s</span>
            </div>
            <div class="shot-dialogue text-ellipsis">
              {{ shot.dialogue || shot.visual_description || '无对白' }}
            </div>
          </div>
        </div>
      </el-card>

      <!-- 右栏：编辑面板 -->
      <el-card class="col-right" shadow="never">
        <template #header>
          <span>分镜编辑 #{{ selectedSeq ?? '-' }}</span>
        </template>
        <el-empty v-if="selectedSeq === null" description="请选择一个分镜" :image-size="60" />
        <div v-else class="edit-form">
          <el-form label-position="top" size="default">
            <el-form-item label="画面描述">
              <el-input
                v-model="editingShot.visual_description"
                type="textarea"
                :rows="3"
                placeholder="描述画面内容..."
              />
            </el-form-item>
            <el-form-item label="景别">
              <el-select v-model="editingShot.shot_type" placeholder="选择景别">
                <el-option v-for="t in shotTypeOptions" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="运镜">
              <el-select v-model="editingShot.camera_movement" placeholder="选择运镜">
                <el-option v-for="m in cameraMoveOptions" :key="m" :label="m" :value="m" />
              </el-select>
            </el-form-item>
            <el-form-item label="时长（秒）">
              <el-input-number v-model="editingShot.duration" :min="1" :max="30" />
            </el-form-item>
            <el-form-item label="对白">
              <el-input
                v-model="editingShot.dialogue"
                type="textarea"
                :rows="2"
                placeholder="角色对白..."
              />
            </el-form-item>
            <el-form-item label="旁白">
              <el-input
                v-model="editingShot.narration"
                type="textarea"
                :rows="2"
                placeholder="旁白内容..."
              />
            </el-form-item>
            <el-form-item label="绘图提示词">
              <el-input
                v-model="editingShot.prompt"
                type="textarea"
                :rows="2"
                placeholder="用于生成画面的提示词..."
              />
            </el-form-item>
          </el-form>
          <el-button type="primary" style="width: 100%" @click="handleSaveShot">
            保存分镜
          </el-button>
        </div>
      </el-card>
    </div>

    <!-- 底部时间轴 -->
    <div class="timeline-bar">
      <div class="timeline-track">
        <div
          v-for="shot in rows"
          :key="shot.key"
          class="timeline-block"
          :style="{ width: `${((Number(shot.duration) || 3) / totalDuration) * 100}%` }"
          :class="{ active: selectedSeq === shot.sequence }"
          @click="selectShot(shot)"
          :title="`#${shot.sequence} ${shot.shot_type || ''}`"
        >
          #{{ shot.sequence }}
        </div>
      </div>
      <div class="timeline-stats">
        <span>总时长：<b>{{ totalDuration }}s</b></span>
        <span :class="durationDiff > 0 ? 'over' : 'under'">
          误差：{{ durationDiff > 0 ? '+' : '' }}{{ durationDiff }}s
        </span>
      </div>
    </div>

    <!-- 节奏预览（SB-05）：按时长占比可视化整体节奏分布 -->
    <el-collapse class="rhythm-collapse">
      <el-collapse-item name="rhythm">
        <template #title>
          <span class="rhythm-title">
            节奏预览（共 {{ rows.length }} 镜，总时长 <b>{{ totalDuration }}s</b>，平均
            {{ avgDuration.toFixed(1) }}s/镜）
          </span>
        </template>
        <el-empty v-if="rows.length === 0" description="暂无分镜" :image-size="60" />
        <div v-else class="rhythm-chart">
          <div v-for="shot in rows" :key="shot.key" class="rhythm-row" @click="selectShot(shot)">
            <span class="rhythm-seq">#{{ shot.sequence }}</span>
            <div class="rhythm-track">
              <div
                class="rhythm-bar"
                :class="{ peak: isPeak(shot), active: selectedSeq === shot.sequence }"
                :style="{ width: rhythmWidth(shot) }"
              ></div>
            </div>
            <span class="rhythm-duration">{{ Number(shot.duration) || 3 }}s</span>
            <el-tag v-if="isPeak(shot)" size="small" type="danger" class="rhythm-peak-tag">
              高潮
            </el-tag>
          </div>
          <div class="rhythm-legend">
            <span>条宽 = 时长占比</span>
            <span>深色长条 = 高潮段落（&gt; 平均时长 × 1.5）</span>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- 底部确认按钮 -->
    <div class="page-footer">
      <el-button type="primary" size="large" :disabled="rows.length === 0" @click="handleConfirm">
        确认分镜，进入生成阶段
        <el-icon class="el-icon--right"><ArrowRight /></el-icon>
      </el-button>
    </div>

    <!-- 连续性检查结果弹窗（SB-06） -->
    <el-dialog v-model="continuityVisible" title="分镜连续性检查结果" width="560px">
      <el-alert
        v-if="continuityResult && !continuityResult.checked"
        type="info"
        :closable="false"
        title="本次检查未完成（AI 服务暂不可用），请稍后重试"
      />
      <template v-else>
        <el-empty
          v-if="!continuityResult || continuityResult.issues.length === 0"
          description="未发现衔接问题"
          :image-size="80"
        />
        <div v-else class="issue-list">
          <div
            v-for="(issue, i) in continuityResult.issues"
            :key="i"
            class="issue-item"
            @click="issueSeqSet.size > 0 && (selectedSeq = issue.between[0] ?? null)"
          >
            <el-tag size="small" :type="severityTagType(issue.severity)" class="issue-severity">
              {{ issue.severity === 'high' ? '严重' : issue.severity === 'medium' ? '中等' : '轻微' }}
            </el-tag>
            <el-tag size="small" type="info">{{ issue.type || '衔接' }}</el-tag>
            <span class="issue-between">
              #{{ issue.between?.[0] ?? '?' }} ↔ #{{ issue.between?.[1] ?? '?' }}
            </span>
            <p class="issue-message">{{ issue.message }}</p>
          </div>
        </div>
        <div v-if="continuityResult && continuityResult.issues.length > 0" class="issue-hint">
          存在问题的分镜卡片已在列表中以橙色边框 + “!” 角标高亮。
        </div>
      </template>
      <template #footer>
        <el-button @click="continuityVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.storyboard-view {
  min-height: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-title {
  font-size: 22px;
  margin: 0;
}

.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  align-items: center;
}

.toolbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}

.duration-label {
  color: var(--ai-text-regular);
}

.duration-unit {
  color: var(--ai-text-secondary);
}

.three-column {
  display: grid;
  grid-template-columns: 240px 1fr 320px;
  gap: 16px;
  height: calc(100vh - 420px);
  min-height: 400px;
}

.col-left,
.col-mid,
.col-right {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.col-left :deep(.el-card__body),
.col-mid :deep(.el-card__body),
.col-right :deep(.el-card__body) {
  flex: 1;
  overflow-y: auto;
}

.script-text {
  line-height: 1.8;
  font-size: 13px;
  color: var(--ai-text-regular);
}

.shot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.shot-card {
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

.shot-thumb {
  position: relative;
  height: 100px;
  background: var(--ai-bg-color);
}

.thumb-img {
  width: 100%;
  height: 100%;
}

.thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ai-text-placeholder);
}

.shot-seq {
  position: absolute;
  top: 4px;
  left: 6px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
}

.shot-meta {
  display: flex;
  gap: 4px;
  padding: 6px 8px;
  flex-wrap: wrap;
  align-items: center;
}

.shot-duration {
  font-size: 12px;
  color: var(--ai-text-secondary);
  margin-left: auto;
}

.shot-dialogue {
  padding: 0 8px 8px;
  font-size: 12px;
  color: var(--ai-text-regular);
}

.edit-form {
  padding: 4px;
}

/* 时间轴 */
.timeline-bar {
  margin-top: 16px;
  padding: 12px 16px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid var(--ai-border-color);
}

.timeline-track {
  display: flex;
  height: 40px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--ai-bg-color);
  margin-bottom: 10px;
}

.timeline-block {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #fff;
  background: var(--ai-primary-color);
  border-right: 1px solid #fff;
  cursor: pointer;
  transition: opacity 0.2s;

  &:hover {
    opacity: 0.85;
  }

  &.active {
    background: var(--ai-primary-dark);
  }
}

.timeline-stats {
  display: flex;
  gap: 24px;
  font-size: 14px;
  color: var(--ai-text-regular);

  .over {
    color: var(--ai-danger-color);
  }

  .under {
    color: var(--ai-success-color);
  }
}

.page-footer {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0;
}

/* 拖拽重排（SB-04） */
.shot-card.dragging {
  opacity: 0.45;
}

.shot-card.drag-over {
  border-color: var(--ai-warning-color, #e6a23c);
  transform: translateY(-2px);
}

.shot-card[draggable='true'] {
  cursor: grab;
}

.shot-card[draggable='true']:active {
  cursor: grabbing;
}

/* 连续性问题高亮（SB-06） */
.shot-card.has-issue {
  border-color: var(--ai-warning-color, #e6a23c);
  box-shadow: 0 0 0 1px var(--ai-warning-color, #e6a23c) inset;
}

.issue-badge {
  position: absolute;
  top: 4px;
  right: 6px;
  width: 16px;
  height: 16px;
  line-height: 16px;
  text-align: center;
  border-radius: 50%;
  background: var(--ai-warning-color, #e6a23c);
  color: #fff;
  font-size: 12px;
  font-weight: bold;
}

.issue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
}

.issue-item {
  padding: 10px 12px;
  border: 1px solid var(--ai-border-color, #e4e7ed);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;

  &:hover {
    background: var(--ai-bg-color, #f5f7fa);
  }
}

.issue-severity {
  margin-right: 6px;
}

.issue-between {
  margin-left: 8px;
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.issue-message {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ai-text-regular);
}

.issue-hint {
  margin-top: 12px;
  font-size: 12px;
  color: var(--ai-text-secondary);
}

/* 节奏预览（SB-05） */
.rhythm-collapse {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--ai-border-color);
  border-radius: 8px;
  padding: 0 16px;
}

.rhythm-title {
  font-size: 14px;
  color: var(--ai-text-regular);
}

.rhythm-chart {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0 8px;
}

.rhythm-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.rhythm-seq {
  width: 36px;
  font-size: 12px;
  color: var(--ai-text-secondary);
  text-align: right;
  flex-shrink: 0;
}

.rhythm-track {
  flex: 1;
  height: 14px;
  background: var(--ai-bg-color);
  border-radius: 7px;
  overflow: hidden;
}

.rhythm-bar {
  height: 100%;
  background: var(--ai-primary-color);
  border-radius: 7px;
  transition: width 0.3s;

  &.peak {
    background: var(--ai-danger-color, #f56c6c);
  }

  &.active {
    outline: 1px solid var(--ai-primary-dark);
    opacity: 0.85;
  }
}

.rhythm-duration {
  width: 34px;
  font-size: 12px;
  color: var(--ai-text-secondary);
  flex-shrink: 0;
}

.rhythm-peak-tag {
  flex-shrink: 0;
}

.rhythm-legend {
  display: flex;
  gap: 16px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--ai-text-placeholder);
}
</style>
