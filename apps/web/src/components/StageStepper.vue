<!--
  五阶段步骤条组件
  展示创作全流程：剧本 → 资产 → 分镜 → 生成 → 审核发布
  根据 current 高亮当前阶段，已解锁阶段可点击跳转
  @file components/StageStepper.vue
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { EditPen, Picture, Film, VideoPlay, Promotion } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

/** 五阶段定义：剧本 → 资产 → 分镜 → 生成 → 审核发布 */
const stages = [
  { key: 'script', title: '剧本', icon: EditPen, route: '/script' },
  { key: 'assets', title: '资产', icon: Picture, route: '/assets' },
  { key: 'storyboard', title: '分镜', icon: Film, route: '/storyboard' },
  { key: 'generate', title: '生成', icon: VideoPlay, route: '/keyframes' },
  { key: 'review', title: '审核发布', icon: Promotion, route: '/review' },
]

/** 阶段键到索引的映射 */
const stageKeyToIndex: Record<string, number> = stages.reduce(
  (acc, s, i) => {
    acc[s.key] = i
    return acc
  },
  {} as Record<string, number>,
)

/** 组件 Props */
interface Props {
  /** 当前阶段索引（0-4），优先级高于 currentStage */
  current?: number
  /** 当前阶段键（如 script / assets），兼容已有页面用法 */
  currentStage?: string
}

const props = defineProps<Props>()

/** 点击阶段时触发，传递阶段索引 */
const emit = defineEmits<{
  (e: 'change', index: number): void
}>()

/**
 * 计算当前激活的阶段索引
 * 优先使用 current（数字），其次根据 currentStage（字符串键）映射
 * @returns 当前阶段索引（0-4），无法确定时返回 0
 */
const activeIndex = computed<number>(() => {
  if (typeof props.current === 'number') {
    return Math.max(0, Math.min(props.current, stages.length - 1))
  }
  if (props.currentStage && props.currentStage in stageKeyToIndex) {
    return stageKeyToIndex[props.currentStage]
  }
  return 0
})

/**
 * 判断某个阶段是否已解锁（已完成或为当前阶段）
 * @param index - 阶段索引
 * @returns 是否已解锁
 */
function isUnlocked(index: number): boolean {
  return index <= activeIndex.value
}

/**
 * 点击阶段项：已解锁阶段跳转到对应页面
 * @param index - 阶段索引
 */
function handleClick(index: number): void {
  if (!isUnlocked(index)) return
  const projectId = route.params.id as string | undefined
  if (!projectId) return
  const targetRoute = stages[index].route
  if (targetRoute) {
    router.push(`/project/${projectId}${targetRoute}`)
  }
  emit('change', index)
}

</script>

<template>
  <div class="stage-stepper">
    <el-steps :active="activeIndex" align-center finish-status="success">
      <el-step
        v-for="(stage, index) in stages"
        :key="stage.key"
        :title="stage.title"
        :class="{ 'is-locked': !isUnlocked(index) }"
        @click="handleClick(index)"
      >
        <template #icon>
          <el-icon class="step-icon">
            <component :is="stage.icon" />
          </el-icon>
        </template>
      </el-step>
    </el-steps>
  </div>
</template>

<style scoped>
.stage-stepper {
  position: relative;
  width: 100%;
  padding: 20px 24px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(10px);
  border: 1px solid var(--ai-border-light);
  border-radius: var(--ai-radius-lg);
  box-shadow: var(--ai-shadow-card);
  margin-bottom: 20px;
}

/* 步骤可点击 */
.stage-stepper :deep(.el-step) {
  cursor: pointer;
}

/* 未解锁阶段禁用点击 */
.stage-stepper :deep(.el-step.is-locked) {
  cursor: not-allowed;
  opacity: 0.45;
}

.step-icon {
  font-size: 18px;
}

/* 当前步骤图标渐变背景 */
.stage-stepper :deep(.el-step__head.is-process) {
  color: var(--ai-primary-color);
  border-color: var(--ai-primary-color);
}

.stage-stepper :deep(.el-step__title.is-process) {
  font-weight: 600;
  color: var(--ai-primary-color);
}
</style>
