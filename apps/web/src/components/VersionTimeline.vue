<!--
  C04 版本时间线
  抽屉形式展示项目历史版本（阶段徽标 + 时间 + 操作人），支持相邻版本差异摘要对比
  提供「回退到此版本」按钮，回退前二次确认并列出影响范围，回退后跳转对应阶段页
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Revision } from '@/types'
import { listRevisions, restoreRevision } from '@/api/revisions'

const route = useRoute()
const router = useRouter()

/** 抽屉是否打开 */
const drawerVisible = ref(false)
/** 版本列表 */
const revisions = ref<Revision[]>([])
/** 加载态 */
const loading = ref(false)
/** 回退中 */
const restoring = ref(false)
/** 当前选中对比的版本（高亮） */
const selectedId = ref<string>('')

/** 阶段标识到中文标签与路由的映射 */
const STAGE_MAP: Record<string, { label: string; route: string }> = {
  script: { label: '剧本', route: '/script' },
  assets: { label: '资产', route: '/assets' },
  character: { label: '角色', route: '/assets' },
  scene: { label: '场景', route: '/assets' },
  storyboard: { label: '分镜', route: '/storyboard' },
  keyframes: { label: '关键帧', route: '/keyframes' },
  video: { label: '视频', route: '/video' },
  voice: { label: '配音', route: '/voice' },
  compose: { label: '合成', route: '/compose' },
  review: { label: '审核', route: '/review' },
}

/**
 * 获取当前项目 ID
 * @returns 项目 ID
 */
const projectId = computed<string>(() => (route.params.id as string) || '')

/**
 * 按创建时间倒序排列的版本列表
 */
const sortedRevisions = computed(() =>
  [...revisions.value].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  ),
)

/**
 * 获取阶段中文标签
 * @param type - 版本类型（阶段）
 * @returns 中文标签
 */
function stageLabel(type: string): string {
  return STAGE_MAP[type]?.label || type
}

/**
 * 获取操作人（从快照中提取，缺省为「系统」）
 * @param revision - 版本对象
 * @returns 操作人名称
 */
function getOperator(revision: Revision): string {
  const snap = revision.snapshot as Record<string, unknown>
  return (snap.operator as string) || (snap.operator_name as string) || '系统'
}

/**
 * 计算相邻版本的差异摘要
 * @param current - 当前版本
 * @param previous - 上一个版本（时间上更早）
 * @returns 差异摘要文本列表
 */
function diffSummary(current: Revision, previous?: Revision): string[] {
  if (!previous) return ['首个版本，无对比数据']
  const cur = current.snapshot as Record<string, unknown>
  const prev = previous.snapshot as Record<string, unknown>
  const allKeys = new Set([...Object.keys(cur), ...Object.keys(prev)])
  const changes: string[] = []
  allKeys.forEach((key) => {
    const curVal = JSON.stringify(cur[key])
    const prevVal = JSON.stringify(prev[key])
    if (curVal !== prevVal) {
      if (prevVal === undefined) changes.push(`新增字段：${key}`)
      else if (curVal === undefined) changes.push(`移除字段：${key}`)
      else changes.push(`更新字段：${key}`)
    }
  })
  return changes.length > 0 ? changes : ['无实质变更']
}

/**
 * 列出回退到指定版本的影响范围
 * @param revision - 目标版本
 * @returns 影响范围描述列表
 */
function getImpactScope(revision: Revision): string[] {
  const snap = revision.snapshot as Record<string, unknown>
  const keys = Object.keys(snap)
  if (keys.length === 0) return ['该版本快照为空，影响范围未知']
  return keys.map((k) => `模块：${k}`)
}

/**
 * 拉取版本列表
 */
async function fetchRevisions(): Promise<void> {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await listRevisions(projectId.value)
    revisions.value = res
  } catch (e) {
    console.error('拉取版本列表失败', e)
  } finally {
    loading.value = false
  }
}

/**
 * 回退到指定版本（二次确认）
 * @param revision - 目标版本
 */
async function handleRestore(revision: Revision): Promise<void> {
  if (!projectId.value) return
  const scope = getImpactScope(revision)
  try {
    await ElMessageBox.confirm(
      `确定回退到「${stageLabel(revision.type)}」版本吗？\n\n影响范围：\n${scope.join('\n')}\n\n回退后将覆盖当前数据，且无法撤销。`,
      '版本回退确认',
      {
        type: 'warning',
        confirmButtonText: '确认回退',
        cancelButtonText: '取消',
        dangerouslyUseHTMLString: false,
      },
    )
    restoring.value = true
    await restoreRevision(projectId.value, revision.id)
    ElMessage.success('版本回退成功')
    drawerVisible.value = false
    // 回退后跳转对应阶段页
    const stageRoute = STAGE_MAP[revision.type]?.route || '/script'
    router.push(`/project/${projectId.value}${stageRoute}`)
  } catch (e) {
    // 用户取消或回退失败
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error('版本回退失败')
    }
  } finally {
    restoring.value = false
  }
}

/**
 * 打开抽屉并拉取数据
 */
function openDrawer(): void {
  drawerVisible.value = true
  fetchRevisions()
}

defineExpose({ openDrawer })

onMounted(() => {
  if (projectId.value) {
    fetchRevisions()
  }
})
</script>

<template>
  <el-drawer
    v-model="drawerVisible"
    title="版本时间线"
    direction="ltr"
    size="520px"
    destroy-on-close
  >
    <div class="version-timeline">
      <el-skeleton v-if="loading" :rows="6" animated />

      <template v-else>
        <el-empty v-if="sortedRevisions.length === 0" description="暂无历史版本" />

        <el-timeline v-else class="timeline">
          <el-timeline-item
            v-for="(revision, index) in sortedRevisions"
            :key="revision.id"
            :timestamp="revision.created_at"
            placement="top"
            :type="index === 0 ? 'primary' : 'info'"
          >
            <el-card
              class="version-card"
              shadow="hover"
              :class="{ selected: selectedId === revision.id }"
              @click="selectedId = revision.id"
            >
              <div class="version-header">
                <el-tag type="primary" effect="plain">
                  {{ stageLabel(revision.type) }}
                </el-tag>
                <span class="operator">操作人：{{ getOperator(revision) }}</span>
              </div>

              <!-- 差异摘要 -->
              <div class="diff-section">
                <div class="diff-title">
                  <el-icon><Rank /></el-icon>
                  与上一版本差异
                </div>
                <ul class="diff-list">
                  <li v-for="(change, i) in diffSummary(revision, sortedRevisions[index + 1])" :key="i">
                    {{ change }}
                  </li>
                </ul>
              </div>

              <div class="version-actions">
                <el-button
                  type="warning"
                  size="small"
                  :loading="restoring"
                  @click.stop="handleRestore(revision)"
                >
                  回退到此版本
                </el-button>
              </div>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.version-timeline {
  height: 100%;
  overflow-y: auto;
  padding: 0 4px;
}

.timeline {
  padding: 8px 0;
}

.version-card {
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  }

  &.selected {
    border-color: var(--ai-primary-color);
  }
}

.version-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.operator {
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.diff-section {
  background: var(--ai-bg-color);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.diff-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ai-text-regular);
  margin-bottom: 6px;
}

.diff-list {
  padding-left: 16px;
  font-size: 12px;
  color: var(--ai-text-regular);
  line-height: 1.8;
}

.version-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
