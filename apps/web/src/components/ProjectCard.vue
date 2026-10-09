<!--
  项目卡片组件
  展示项目封面、标题、描述、阶段状态徽标、更新时间
  支持点击进入项目、更多操作（重命名、删除）
  @file components/ProjectCard.vue
-->
<script setup lang="ts">
import { computed } from 'vue'
import { Picture, MoreFilled, Edit, Delete, Clock } from '@element-plus/icons-vue'
import type { Project } from '@/types'

/** 组件 Props */
interface Props {
  /** 项目数据 */
  project: Project
}

const props = defineProps<Props>()

/** 事件定义 */
const emit = defineEmits<{
  /** 点击卡片主体：进入项目 */
  (e: 'click', project: Project): void
  /** 重命名项目 */
  (e: 'rename', project: Project): void
  /** 删除项目 */
  (e: 'delete', project: Project): void
}>()

/** 项目状态与徽标文案/类型映射 */
const statusMap: Record<
  string,
  { text: string; type: 'info' | 'primary' | 'success' | 'warning' | 'danger' }
> = {
  draft: { text: '草稿', type: 'info' },
  script: { text: '剧本创作中', type: 'primary' },
  assets: { text: '资产制作中', type: 'primary' },
  storyboard: { text: '分镜设计中', type: 'warning' },
  generating: { text: '生成中', type: 'warning' },
  review: { text: '待审核', type: 'warning' },
  done: { text: '已完成', type: 'success' },
}

/** 当前状态对应的徽标信息 */
const statusInfo = computed(
  () => statusMap[props.project.status] || { text: '未知', type: 'info' as const },
)

/**
 * 将更新时间格式化为相对友好文本
 * @param time - ISO 时间字符串
 * @returns 格式化后的时间文本（如：3 小时前）
 */
function formatTime(time: string): string {
  const date = new Date(time)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return date.toLocaleDateString('zh-CN')
}

/**
 * 触发重命名事件（阻止冒泡避免触发卡片点击）
 */
function handleRename(): void {
  emit('rename', props.project)
}

/**
 * 触发删除事件（阻止冒泡避免触发卡片点击）
 */
function handleDelete(): void {
  emit('delete', props.project)
}
</script>

<template>
  <div class="project-card" @click="emit('click', project)">
    <!-- 封面 -->
    <div class="card-cover">
      <img v-if="project.cover_url" :src="project.cover_url" :alt="project.title" />
      <div v-else class="cover-placeholder">
        <el-icon :size="40"><Picture /></el-icon>
      </div>
      <el-tag class="status-tag" :type="statusInfo.type" effect="dark" size="small">
        {{ statusInfo.text }}
      </el-tag>
    </div>

    <!-- 内容区 -->
    <div class="card-body">
      <div class="card-header">
        <h3 class="card-title text-ellipsis">{{ project.title }}</h3>
        <el-dropdown trigger="click" @click.stop>
          <el-icon class="more-btn" @click.stop><MoreFilled /></el-icon>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="handleRename">
                <el-icon><Edit /></el-icon>重命名
              </el-dropdown-item>
              <el-dropdown-item @click="handleDelete" divided>
                <el-icon><Delete /></el-icon>删除
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <p v-if="project.genre" class="card-desc text-ellipsis">
        {{ project.genre }}
      </p>

      <div class="card-tags">
        <el-tag size="small" effect="plain" type="info">
          {{ project.status || '未开始' }}
        </el-tag>
      </div>

      <div class="card-footer">
        <el-icon><Clock /></el-icon>
        <span>{{ formatTime(project.updated_at) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.project-card {
  background-color: var(--ai-bg-card);
  border-radius: var(--ai-radius-lg);
  overflow: hidden;
  cursor: pointer;
  transition: all var(--ai-transition-base);
  border: 1px solid var(--ai-border-light);
  box-shadow: var(--ai-shadow-card);
  height: 100%;
  display: flex;
  flex-direction: column;

  &:hover {
    box-shadow: var(--ai-shadow-aurora);
    transform: translateY(-4px);
    border-color: var(--ai-primary-light);
  }
}

.card-cover {
  position: relative;
  height: 150px;
  background: var(--ai-gradient-aurora);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform var(--ai-transition-base);
  }

  &:hover img {
    transform: scale(1.05);
  }
}

.cover-placeholder {
  color: rgba(255, 255, 255, 0.85);
  filter: drop-shadow(0 2px 8px rgba(255, 255, 255, 0.3));
}

.status-tag {
  position: absolute;
  top: 10px;
  right: 10px;
  border-radius: var(--ai-radius-full);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.card-body {
  padding: 16px 18px 18px;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ai-text-primary);
  flex: 1;
  letter-spacing: -0.01em;
}

.more-btn {
  font-size: 16px;
  color: var(--ai-text-secondary);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--ai-radius-full);
  transition: all var(--ai-transition-fast);

  &:hover {
    color: var(--ai-primary-color);
    background: var(--ai-bg-subtle);
  }
}

.card-desc {
  font-size: 13px;
  color: var(--ai-text-secondary);
  margin: 8px 0 12px;
}

.card-tags {
  margin-bottom: 12px;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ai-text-secondary);
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--ai-border-light);
}
</style>
