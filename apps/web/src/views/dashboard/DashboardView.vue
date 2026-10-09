<!--
  工作台主页
  展示欢迎栏、新建项目入口、最近项目、项目列表、创作统计
  支持搜索筛选、重命名、删除等操作
  @file views/dashboard/DashboardView.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import type { Project, ProjectStats } from '@/types'
import { listProjects, deleteProject, recentProjects, projectStats, updateProject } from '@/api/projects'
import { getUsage, getQuota } from '@/api/users'
import { useUserStore } from '@/stores/user'
import { useProjectStore } from '@/stores/project'
import ProjectCard from '@/components/ProjectCard.vue'
import NewProjectDialog from './NewProjectDialog.vue'

const router = useRouter()
const userStore = useUserStore()
const projectStore = useProjectStore()

/** 项目列表 */
const projects = ref<Project[]>([])
/** 最近编辑项目（置顶 3 个） */
const recentList = ref<Project[]>([])
/** 项目统计 */
const stats = ref<ProjectStats>({ total: 0, in_progress: 0, completed: 0 })
/** 使用量统计 */
const usage = ref({ images_count: 0, video_seconds: 0, projects_count: 0 })
/** 配额信息 */
const quota = ref({ credits: 0 })

/** 列表加载状态 */
const loading = ref(false)
/** 骨架屏加载状态 */
const skeletonLoading = ref(true)

/** 搜索关键词 */
const keyword = ref('')
/** 状态筛选 */
const statusFilter = ref('')
/** 排序方式 */
const sortBy = ref<'updated_at' | 'created_at' | 'name'>('updated_at')

/** 状态筛选项 */
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '剧本创作中', value: 'script' },
  { label: '资产制作中', value: 'assets' },
  { label: '分镜设计中', value: 'storyboard' },
  { label: '生成中', value: 'generating' },
  { label: '待审核', value: 'review' },
  { label: '已完成', value: 'done' },
]

/** 新建项目弹窗可见性 */
const newProjectVisible = ref(false)

/** 重命名弹窗 */
const renameVisible = ref(false)
const renamingProject = ref<Project | null>(null)
const renameName = ref('')
const renameLoading = ref(false)

/** 统计图表 DOM 引用 */
const chartRef = ref<HTMLElement>()
/** echarts 实例 */
let chartInstance: echarts.ECharts | null = null

/** 筛选并排序后的项目列表 */
const filteredProjects = computed<Project[]>(() => {
  let list = [...projects.value]
  if (keyword.value) {
    const kw = keyword.value.toLowerCase()
    list = list.filter(
      (p) =>
        p.name.toLowerCase().includes(kw) ||
        (p.description || '').toLowerCase().includes(kw),
    )
  }
  if (statusFilter.value) {
    list = list.filter((p) => p.status === statusFilter.value)
  }
  if (sortBy.value === 'updated_at') {
    list.sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
  } else if (sortBy.value === 'created_at') {
    list.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )
  } else {
    list.sort((a, b) => a.name.localeCompare(b.name))
  }
  return list
})

/** 今日新建项目数 */
const todayCount = computed(() => {
  const today = new Date().toDateString()
  return projects.value.filter((p) => new Date(p.created_at).toDateString() === today).length
})

/** 本月新建项目数 */
const monthCount = computed(() => {
  const now = new Date()
  return projects.value.filter((p) => {
    const d = new Date(p.created_at)
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
  }).length
})

/**
 * 加载工作台全部数据（项目列表、最近项目、统计、使用量、配额）
 */
async function loadData(): Promise<void> {
  skeletonLoading.value = true
  loading.value = true
  try {
    const results = await Promise.allSettled([
      listProjects({ page: 1, page_size: 100 }),
      recentProjects(),
      projectStats(),
      getUsage(),
      getQuota(),
    ])
    const [listRes, recentRes, statsRes, usageRes, quotaRes] = results
    if (listRes.status === 'fulfilled') {
      projects.value = listRes.value.list
      projectStore.projectList = listRes.value.list
    }
    if (recentRes.status === 'fulfilled') {
      recentList.value = recentRes.value.slice(0, 3)
    }
    if (statsRes.status === 'fulfilled') {
      stats.value = statsRes.value
    }
    if (usageRes.status === 'fulfilled') {
      usage.value = usageRes.value
    }
    if (quotaRes.status === 'fulfilled') {
      quota.value = quotaRes.value
    }
  } catch (err) {
    console.error('加载数据失败：', err)
    ElMessage.error('加载数据失败')
  } finally {
    loading.value = false
    skeletonLoading.value = false
    nextTick(() => initChart())
  }
}

/**
 * 初始化项目状态分布饼图
 */
function initChart(): void {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
  // 从项目列表统计各状态数量
  const inProgressCount = projects.value.filter(
    (p) => p.status && p.status !== 'draft' && p.status !== 'done',
  ).length
  const completedCount = projects.value.filter((p) => p.status === 'done').length
  const draftCount = projects.value.filter((p) => p.status === 'draft').length
  chartInstance.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 12 } },
    series: [
      {
        name: '项目状态',
        type: 'pie',
        radius: ['45%', '70%'],
        avoidLabelOverlap: false,
        label: { show: false },
        labelLine: { show: false },
        data: [
          { value: inProgressCount, name: '进行中', itemStyle: { color: '#409eff' } },
          { value: completedCount, name: '已完成', itemStyle: { color: '#67c23a' } },
          { value: draftCount, name: '草稿', itemStyle: { color: '#909399' } },
        ],
      },
    ],
  })
}

/**
 * 进入项目（跳转到剧本页）
 * @param project - 项目对象
 */
function enterProject(project: Project): void {
  projectStore.setCurrent(project)
  router.push(`/project/${project.id}/script`)
}

/**
 * 打开新建项目弹窗
 */
function openNewProject(): void {
  newProjectVisible.value = true
}

/**
 * 项目创建成功回调：关闭弹窗并进入项目剧本页
 * @param project - 新建的项目
 */
function handleProjectCreated(project: Project): void {
  newProjectVisible.value = false
  ElMessage.success('项目创建成功')
  enterProject(project)
}

/**
 * 打开重命名弹窗
 * @param project - 要重命名的项目
 */
function handleRename(project: Project): void {
  renamingProject.value = project
  renameName.value = project.title
  renameVisible.value = true
}

/**
 * 确认重命名项目
 */
async function confirmRename(): Promise<void> {
  if (!renamingProject.value || !renameName.value.trim()) return
  renameLoading.value = true
  try {
    const updated = await updateProject(renamingProject.value.id, {
      title: renameName.value.trim(),
    })
    const idx = projects.value.findIndex((p) => p.id === updated.id)
    if (idx !== -1) projects.value[idx] = updated
    const recentIdx = recentList.value.findIndex((p) => p.id === updated.id)
    if (recentIdx !== -1) recentList.value[recentIdx] = updated
    ElMessage.success('重命名成功')
    renameVisible.value = false
  } catch (err) {
    console.error('重命名失败：', err)
  } finally {
    renameLoading.value = false
  }
}

/**
 * 删除项目（二次确认）
 * @param project - 要删除的项目
 */
async function handleDelete(project: Project): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定要删除项目「${project.title}」吗？此操作不可恢复。`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
    await deleteProject(project.id)
    projects.value = projects.value.filter((p) => p.id !== project.id)
    recentList.value = recentList.value.filter((p) => p.id !== project.id)
    ElMessage.success('删除成功')
  } catch {
    // 用户取消删除，无需提示
  }
}

/**
 * 格式化视频时长（秒 → 可读文本）
 * @param seconds - 秒数
 * @returns 格式化后的时长文本
 */
function formatDuration(seconds: number): string {
  if (!seconds) return '0 分钟'
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins} 分钟`
  const hours = Math.floor(mins / 60)
  return `${hours} 小时 ${mins % 60} 分`
}

/**
 * 窗口大小变化时重置图表尺寸
 */
function handleResize(): void {
  chartInstance?.resize()
}

onMounted(() => {
  loadData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- 顶部欢迎栏 -->
    <div class="welcome-bar">
      <div class="welcome-info">
        <h2 class="welcome-title">
          你好，{{ userStore.userInfo?.nickname || userStore.userInfo?.username || '创作者' }} 👋
        </h2>
        <p class="welcome-subtitle">
          共 {{ projects.length }} 个项目，开启你的漫剧创作吧
        </p>
      </div>
      <div class="welcome-actions">
        <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        <el-button type="primary" :icon="Plus" size="large" @click="openNewProject">
          新建项目
        </el-button>
      </div>
    </div>

    <!-- 创作统计卡片 -->
    <div class="stats-section">
      <el-card class="stat-card" shadow="hover">
        <div class="stat-content">
          <div class="stat-icon stat-icon-blue">
            <el-icon :size="24"><Folder /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ projects.length }}</div>
            <div class="stat-label">项目总数</div>
          </div>
        </div>
      </el-card>

      <el-card class="stat-card" shadow="hover">
        <div class="stat-content">
          <div class="stat-icon stat-icon-green">
            <el-icon :size="24"><Picture /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ usage.image_count }}</div>
            <div class="stat-label">生成图片数</div>
          </div>
        </div>
      </el-card>

      <el-card class="stat-card" shadow="hover">
        <div class="stat-content">
          <div class="stat-icon stat-icon-orange">
            <el-icon :size="24"><VideoPlay /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ formatDuration(usage.video_duration) }}</div>
            <div class="stat-label">视频总时长</div>
          </div>
        </div>
      </el-card>

      <el-card class="stat-card" shadow="hover">
        <div class="stat-content">
          <div class="stat-icon stat-icon-purple">
            <el-icon :size="24"><Coin /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ quota.quota }}</div>
            <div class="stat-label">剩余点数</div>
          </div>
        </div>
      </el-card>

      <!-- 状态分布图表 -->
      <el-card class="chart-card" shadow="hover">
        <template #header>
          <span>项目状态分布</span>
        </template>
        <div ref="chartRef" class="chart-container"></div>
      </el-card>
    </div>

    <!-- 最近编辑项目 -->
    <div v-if="!skeletonLoading && recentList.length > 0" class="recent-section">
      <div class="section-header">
        <h3 class="section-title">最近编辑</h3>
      </div>
      <div class="recent-grid">
        <el-card
          v-for="project in recentList"
          :key="project.id"
          class="recent-card"
          shadow="hover"
          @click="enterProject(project)"
        >
          <div class="recent-card-body">
            <div class="recent-cover">
              <img v-if="project.cover_url" :src="project.cover_url" :alt="project.title" />
              <el-icon v-else :size="28"><Picture /></el-icon>
            </div>
            <div class="recent-info">
              <h4 class="recent-title text-ellipsis">{{ project.title }}</h4>
              <p class="recent-desc text-ellipsis">{{ project.genre || '暂无描述' }}</p>
              <el-tag size="small" type="primary" effect="plain">
                {{ project.status || '未开始' }}
              </el-tag>
            </div>
            <el-button type="primary" link class="continue-btn">继续创作 →</el-button>
          </div>
        </el-card>
      </div>
    </div>

    <!-- 项目列表区 -->
    <div class="projects-section">
      <div class="section-header">
        <h3 class="section-title">全部项目</h3>
        <span class="project-count">共 {{ filteredProjects.length }} 个</span>
      </div>

      <!-- 搜索筛选栏 -->
      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="搜索项目名称或描述"
          :prefix-icon="Search"
          clearable
          class="filter-search"
        />
        <el-select v-model="statusFilter" placeholder="状态筛选" class="filter-select">
          <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="sortBy" placeholder="排序" class="filter-select">
          <el-option label="最近更新" value="updated_at" />
          <el-option label="最近创建" value="created_at" />
          <el-option label="名称排序" value="name" />
        </el-select>
      </div>

      <!-- 骨架屏 -->
      <el-skeleton v-if="skeletonLoading" :rows="4" animated>
        <template #template>
          <div class="skeleton-grid">
            <el-skeleton-item
              v-for="i in 6"
              :key="i"
              variant="rect"
              class="skeleton-card"
              style="height: 220px"
            />
          </div>
        </template>
      </el-skeleton>

      <!-- 项目卡片列表 -->
      <div v-else-if="filteredProjects.length > 0" class="project-grid">
        <ProjectCard
          v-for="project in filteredProjects"
          :key="project.id"
          :project="project"
          @click="enterProject"
          @rename="handleRename"
          @delete="handleDelete"
        />
      </div>

      <!-- 空状态 -->
      <el-empty v-else description="还没有项目，快来创建你的第一个漫剧项目吧">
        <el-button type="primary" :icon="Plus" @click="openNewProject">
          创建第一个漫剧项目
        </el-button>
      </el-empty>
    </div>

    <!-- 新建项目弹窗 -->
    <NewProjectDialog
      v-model="newProjectVisible"
      @created="handleProjectCreated"
    />

    <!-- 重命名弹窗 -->
    <el-dialog v-model="renameVisible" title="重命名项目" width="420px">
      <el-input v-model="renameName" placeholder="请输入新的项目名称" maxlength="50" show-word-limit />
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" :loading="renameLoading" @click="confirmRename">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 0;
}

/* 欢迎栏 */
.welcome-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0 24px;
  flex-wrap: wrap;
  gap: 16px;
}

.welcome-title {
  font-size: 26px;
  font-weight: 700;
  color: var(--ai-text-primary);
  margin-bottom: 6px;
  letter-spacing: -0.02em;
}

.welcome-subtitle {
  font-size: 14px;
  color: var(--ai-text-secondary);
}

.welcome-actions {
  display: flex;
  gap: 12px;
}

/* 统计卡片 */
.stats-section {
  display: grid;
  grid-template-columns: repeat(4, 1fr) 1.4fr;
  gap: 16px;
  margin-bottom: 28px;
}

.stat-card {
  border-radius: var(--ai-radius-md);
  transition: all var(--ai-transition-base);

  &:hover {
    transform: translateY(-2px);
    box-shadow: var(--ai-shadow-hover);
  }
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: var(--ai-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.stat-icon-blue {
  background: linear-gradient(135deg, #6fa8ff, #3b7ee6);
}
.stat-icon-green {
  background: linear-gradient(135deg, #4ade80, #1b9d63);
}
.stat-icon-orange {
  background: linear-gradient(135deg, #ffb5c5, #e67fa0);
}
.stat-icon-purple {
  background: linear-gradient(135deg, #9b8ae6, #6fa8ff);
}

.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--ai-text-primary);
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.stat-label {
  font-size: 13px;
  color: var(--ai-text-secondary);
  margin-top: 2px;
}

.chart-card {
  border-radius: var(--ai-radius-md);
}

.chart-container {
  height: 180px;
  width: 100%;
}

/* 最近编辑 */
.recent-section {
  margin-bottom: 28px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--ai-text-primary);
  letter-spacing: -0.01em;
}

.project-count {
  font-size: 13px;
  color: var(--ai-text-secondary);
}

.recent-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.recent-card {
  cursor: pointer;
  border-radius: var(--ai-radius-md);
  transition: all var(--ai-transition-base);

  &:hover {
    transform: translateY(-2px);
    box-shadow: var(--ai-shadow-glow);
  }
}

.recent-card-body {
  display: flex;
  align-items: center;
  gap: 14px;
}

.recent-cover {
  width: 56px;
  height: 56px;
  border-radius: var(--ai-radius-sm);
  background: var(--ai-gradient-aurora);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  overflow: hidden;
}

.recent-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.recent-info {
  flex: 1;
  min-width: 0;
}

.recent-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ai-text-primary);
  margin-bottom: 4px;
}

.recent-desc {
  font-size: 12px;
  color: var(--ai-text-secondary);
  margin-bottom: 6px;
}

.continue-btn {
  flex-shrink: 0;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.filter-search {
  flex: 1;
  min-width: 240px;
}

.filter-select {
  width: 160px;
}

/* 项目网格 */
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

/* 骨架屏网格 */
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.skeleton-card {
  border-radius: var(--ai-radius-md);
}

/* 响应式 */
@media (max-width: 1200px) {
  .stats-section {
    grid-template-columns: repeat(2, 1fr);
  }
  .chart-card {
    grid-column: span 2;
  }
}

@media (max-width: 768px) {
  .stats-section {
    grid-template-columns: 1fr;
  }
  .chart-card {
    grid-column: span 1;
  }
  .recent-grid {
    grid-template-columns: 1fr;
  }
}
</style>
