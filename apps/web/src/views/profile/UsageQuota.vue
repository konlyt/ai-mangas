<!--
  P14 使用量与配额页
  展示剩余点数（不足 20% 黄色预警）、用量图表（API 次数、图片/视频量、存储，按日/周/月切换）、
  点数消耗明细表（模型/时间/点数），提供「充值」入口
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import type { UserQuota, UserUsage } from '@/types'
import { getQuota, getUsage } from '@/api/users'

// 注册 ECharts 模块
use([
  CanvasRenderer,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
])

const router = useRouter()

/** 加载态 */
const loading = ref(false)
/** 配额信息 */
const quota = ref<UserQuota | null>(null)
/** 使用量信息 */
const usage = ref<UserUsage | null>(null)
/** 图表时间维度：日 / 周 / 月 */
const timeRange = ref<'day' | 'week' | 'month'>('day')

/** 点数消耗明细表（演示数据，实际应从后端获取） */
const consumptionList = ref([
  { id: 1, model: 'GPT-4o', type: '文本', time: '2026-10-06 10:30', credits: 12 },
  { id: 2, model: 'Stable Diffusion XL', type: '图像', time: '2026-10-06 09:15', credits: 8 },
  { id: 3, model: 'Kling 1.6', type: '视频', time: '2026-10-05 22:40', credits: 120 },
  { id: 4, model: 'Sambert TTS', type: '语音', time: '2026-10-05 18:20', credits: 3 },
  { id: 5, model: 'Midjourney V6', type: '图像', time: '2026-10-05 14:05', credits: 25 },
  { id: 6, model: 'Qwen2.5-72B', type: '文本', time: '2026-10-04 16:30', credits: 6 },
])

/**
 * 计算剩余点数百分比
 * @returns 剩余百分比（0-100）
 */
const remainingPercent = computed(() => {
  if (!quota.value) return 0
  const used = usage.value?.cost_points || 0
  const total = quota.value.quota + used
  if (total <= 0) return 0
  return Math.round((quota.value.quota / total) * 100)
})

/**
 * 是否低于 20% 预警线
 */
const isLowQuota = computed(() => remainingPercent.value <= 20)

/**
 * 根据时间维度生成图表 X 轴标签
 * @returns 日期标签数组
 */
function generateXAxis(): string[] {
  const labels: string[] = []
  const now = new Date()
  if (timeRange.value === 'day') {
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now)
      d.setDate(now.getDate() - i)
      labels.push(`${d.getMonth() + 1}/${d.getDate()}`)
    }
  } else if (timeRange.value === 'week') {
    for (let i = 3; i >= 0; i--) {
      const d = new Date(now)
      d.setDate(now.getDate() - i * 7)
      labels.push(`第${Math.ceil((d.getDate() + new Date(d.getFullYear(), d.getMonth(), 1).getDay()) / 7)}周`)
    }
  } else {
    for (let i = 5; i >= 0; i--) {
      const d = new Date(now)
      d.setMonth(now.getMonth() - i)
      labels.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
    }
  }
  return labels
}

/**
 * 根据时间维度生成随机演示数据
 * @param base - 基数
 * @returns 数据数组
 */
function generateSeries(base: number): number[] {
  const len = timeRange.value === 'day' ? 7 : timeRange.value === 'week' ? 4 : 6
  return Array.from({ length: len }, () => Math.round(base * (0.5 + Math.random())))
}

/**
 * ECharts 图表配置
 */
const chartOption = computed(() => {
  const xAxis = generateXAxis()
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['API 调用次数', '图片生成量', '视频生成(秒)'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: xAxis },
    yAxis: { type: 'value' },
    series: [
      {
        name: 'API 调用次数',
        type: 'line',
        smooth: true,
        data: generateSeries(150),
        areaStyle: { opacity: 0.1 },
      },
      {
        name: '图片生成量',
        type: 'bar',
        data: generateSeries(30),
      },
      {
        name: '视频生成(秒)',
        type: 'line',
        smooth: true,
        data: generateSeries(60),
      },
    ],
  }
})

/**
 * 加载配额与使用量数据
 */
async function loadData(): Promise<void> {
  loading.value = true
  try {
    const [q, u] = await Promise.all([getQuota(), getUsage()])
    quota.value = q
    usage.value = u
  } catch (e) {
    console.error('加载配额数据失败', e)
  } finally {
    loading.value = false
  }
}

/**
 * 跳转充值（订单）页
 */
function goRecharge(): void {
  router.push('/profile/orders')
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="usage-quota" v-loading="loading">
    <h2 class="page-title">使用量与配额</h2>

    <!-- 剩余点数卡片 -->
    <el-card class="quota-card" shadow="never">
      <div class="quota-content">
        <div class="quota-left">
          <div class="quota-label">剩余点数</div>
          <div class="quota-value" :class="{ low: isLowQuota }">
            {{ quota?.quota ?? 0 }}
          </div>
          <div class="quota-sub">
            已用 {{ usage?.cost_points ?? 0 }} 点 ·
            会员等级：<el-tag size="small" type="primary">Lv.{{ quota?.vip_level ?? 0 }}</el-tag>
          </div>
        </div>
        <div class="quota-right">
          <el-progress
            :percentage="remainingPercent"
            :color="isLowQuota ? '#e6a23c' : '#67c23a'"
            :stroke-width="14"
            :text-inside="true"
            status=""
          />
          <el-alert
            v-if="isLowQuota"
            title="点数不足 20%，建议及时充值以免影响使用"
            type="warning"
            show-icon
            :closable="false"
            style="margin-top: 12px"
          />
          <el-button type="primary" class="recharge-btn" @click="goRecharge">
            <el-icon><Wallet /></el-icon>
            立即充值
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 使用量统计概览 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon video"><el-icon><VideoPlay /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ usage?.video_duration ?? 0 }}</div>
            <div class="stat-label">视频时长（秒）</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon image"><el-icon><Picture /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ usage?.image_count ?? 0 }}</div>
            <div class="stat-label">图片数量</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon audio"><el-icon><Coin /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ usage?.cost_points ?? 0 }}</div>
            <div class="stat-label">累计消耗（点）</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon project"><el-icon><Folder /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ usage?.project_count ?? 0 }}</div>
            <div class="stat-label">项目数量</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 用量图表 -->
    <el-card class="chart-card" shadow="never">
      <template #header>
        <div class="chart-header">
          <span class="card-title">用量趋势</span>
          <el-radio-group v-model="timeRange" size="small">
            <el-radio-button label="day">按日</el-radio-button>
            <el-radio-button label="week">按周</el-radio-button>
            <el-radio-button label="month">按月</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <v-chart :option="chartOption" style="height: 360px" autoresize />
    </el-card>

    <!-- 点数消耗明细 -->
    <el-card class="detail-card" shadow="never">
      <template #header>
        <span class="card-title">点数消耗明细</span>
      </template>
      <el-table :data="consumptionList" stripe>
        <el-table-column prop="model" label="模型" />
        <el-table-column prop="type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="time" label="时间" width="180" />
        <el-table-column prop="credits" label="消耗点数" width="120">
          <template #default="{ row }">
            <span class="credit-value">-{{ row.credits }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.usage-quota {
  max-width: 1100px;
  margin: 0 auto;
}

.page-title {
  font-size: 20px;
  margin-bottom: 24px;
  color: var(--ai-text-primary);
}

.quota-card {
  margin-bottom: 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border: none;
}

.quota-card :deep(.el-card__body) {
  padding: 28px;
}

.quota-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 32px;
}

.quota-label {
  font-size: 14px;
  opacity: 0.85;
  margin-bottom: 8px;
}

.quota-value {
  font-size: 42px;
  font-weight: 700;
  line-height: 1;

  &.low {
    color: #ffd54f;
  }
}

.quota-sub {
  margin-top: 12px;
  font-size: 13px;
  opacity: 0.9;
  display: flex;
  align-items: center;
  gap: 8px;
}

.expire {
  opacity: 0.8;
}

.quota-right {
  flex: 1;
  max-width: 420px;
}

.quota-right :deep(.el-progress__text) {
  color: #fff;
}

.recharge-btn {
  margin-top: 12px;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
}

.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #fff;

  &.video { background: #667eea; }
  &.image { background: #f093fb; }
  &.audio { background: #4facfe; }
  &.project { background: #43e97b; }
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--ai-text-primary);
}

.stat-label {
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.chart-card {
  margin-bottom: 20px;
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
}

.detail-card {
  margin-bottom: 20px;
}

.credit-value {
  color: var(--ai-danger-color);
  font-weight: 600;
}
</style>
