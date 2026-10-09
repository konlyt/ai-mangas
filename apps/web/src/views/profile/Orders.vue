<!--
  P16 订单与充值页
  展示套餐权益对比表（基础/专业/企业）、月卡/年卡选择、订单列表（状态/金额/发票申请）
  提供充值入口，调用后端 recharge 接口完成下单
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/api/request'

/** 套餐定义 */
interface Plan {
  /** 套餐标识 */
  key: string
  /** 套餐名称 */
  name: string
  /** 月卡价格（元） */
  monthly_price: number
  /** 年卡价格（元） */
  yearly_price: number
  /** 点数额度 */
  credits: number
  /** 权益列表 */
  features: string[]
  /** 是否推荐 */
  recommended?: boolean
}

/** 订单项数据结构 */
interface OrderItem {
  /** 订单 ID */
  id: string
  /** 套餐名称 */
  plan_name: string
  /** 周期 */
  period: '月卡' | '年卡'
  /** 金额（元） */
  amount: number
  /** 订单状态 */
  status: 'pending' | 'paid' | 'failed' | 'refunded'
  /** 创建时间 */
  created_at: string
  /** 是否已申请发票 */
  invoiced: boolean
}

/** 套餐列表 */
const plans: Plan[] = [
  {
    key: 'basic',
    name: '基础版',
    monthly_price: 29,
    yearly_price: 290,
    credits: 1000,
    features: ['1000 点数/月', '基础文本模型', '每日 50 张图片', '社区支持'],
  },
  {
    key: 'pro',
    name: '专业版',
    monthly_price: 99,
    yearly_price: 990,
    credits: 5000,
    features: ['5000 点数/月', '全部文本与图像模型', '每日 200 张图片', '视频生成 5 分钟', '优先队列', '邮件支持'],
    recommended: true,
  },
  {
    key: 'enterprise',
    name: '企业版',
    monthly_price: 299,
    yearly_price: 2990,
    credits: 20000,
    features: ['20000 点数/月', '全部模型不限量', '视频生成 30 分钟', 'TTS 不限次', '专属客服', 'API 接入', 'SLA 保障'],
  },
]

/** 周期选择：月卡 / 年卡 */
const billingCycle = ref<'monthly' | 'yearly'>('monthly')

/** 当前选中的套餐 */
const selectedPlanKey = ref<string>('pro')

/** 加载态 */
const loading = ref(false)
/** 充值中 */
const recharging = ref(false)
/** 订单列表 */
const orderList = ref<OrderItem[]>([])

/**
 * 获取套餐显示价格（根据当前周期）
 * @param plan - 套餐对象
 * @returns 价格数值
 */
function getPrice(plan: Plan): number {
  return billingCycle.value === 'monthly' ? plan.monthly_price : plan.yearly_price
}

/** 选中套餐对象 */
const selectedPlan = computed(() => plans.find((p) => p.key === selectedPlanKey.value) || plans[0])

/** 订单状态中文标签映射 */
const STATUS_LABEL: Record<OrderItem['status'], { label: string; type: 'info' | 'success' | 'danger' | 'warning' }> = {
  pending: { label: '待支付', type: 'warning' },
  paid: { label: '已支付', type: 'success' },
  failed: { label: '支付失败', type: 'danger' },
  refunded: { label: '已退款', type: 'info' },
}

/**
 * 拉取订单列表
 */
async function fetchOrders(): Promise<void> {
  loading.value = true
  try {
    const res = await request.get('/orders')
    orderList.value = res as unknown as OrderItem[]
  } catch (e) {
    console.error('拉取订单列表失败', e)
    orderList.value = []
  } finally {
    loading.value = false
  }
}

/**
 * 充值（创建订单）
 */
async function recharge(): Promise<void> {
  recharging.value = true
  try {
    await request.post('/orders/recharge', {
      plan_key: selectedPlanKey.value,
      cycle: billingCycle.value,
    })
    ElMessage.success('订单已创建，请完成支付')
    fetchOrders()
  } catch (e) {
    ElMessage.error('创建订单失败')
  } finally {
    recharging.value = false
  }
}

/**
 * 申请发票
 * @param order - 订单对象
 */
async function applyInvoice(order: OrderItem): Promise<void> {
  try {
    await ElMessageBox.prompt('请输入发票抬头', '申请发票', {
      confirmButtonText: '提交申请',
      cancelButtonText: '取消',
      inputPlaceholder: '请输入发票抬头',
    })
    await request.post(`/orders/${order.id}/invoice`)
    order.invoiced = true
    ElMessage.success('发票申请已提交')
  } catch (e) {
    // 用户取消，不提示
  }
}

onMounted(() => {
  fetchOrders()
})
</script>

<template>
  <div class="orders-page" v-loading="loading">
    <h2 class="page-title">套餐与订单</h2>

    <!-- 套餐权益对比表 -->
    <el-card shadow="never" class="plan-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">套餐权益对比</span>
          <el-radio-group v-model="billingCycle" size="small">
            <el-radio-button label="monthly">月卡</el-radio-button>
            <el-radio-button label="yearly">年卡（省 2 个月）</el-radio-button>
          </el-radio-group>
        </div>
      </template>

      <el-table :data="plans" style="width: 100%">
        <el-table-column prop="name" label="套餐" width="120">
          <template #default="{ row }: { row: any }">
            <div class="plan-name-cell">
              <span>{{ row.name }}</span>
              <el-tag v-if="row.recommended" type="danger" size="small" effect="dark">推荐</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="月卡价格" width="120">
          <template #default="{ row }: { row: any }">¥{{ row.monthly_price }}/月</template>
        </el-table-column>
        <el-table-column label="年卡价格" width="120">
          <template #default="{ row }: { row: any }">¥{{ row.yearly_price }}/年</template>
        </el-table-column>
        <el-table-column label="点数额度" width="120">
          <template #default="{ row }: { row: any }">{{ row.credits }} 点</template>
        </el-table-column>
        <el-table-column label="权益">
          <template #default="{ row }: { row: any }">
            <div class="features">
              <span v-for="(f, i) in row.features" :key="i" class="feature-item">
                <el-icon color="#67c23a"><CircleCheck /></el-icon>
                {{ f }}
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 充值区 -->
    <el-card shadow="never" class="recharge-card">
      <template #header>
        <span class="card-title">选择套餐充值</span>
      </template>
      <div class="plan-selector">
        <div
          v-for="plan in plans"
          :key="plan.key"
          class="plan-option"
          :class="{ active: selectedPlanKey === plan.key, recommended: plan.recommended }"
          @click="selectedPlanKey = plan.key"
        >
          <div class="po-name">{{ plan.name }}</div>
          <div class="po-price">
            <span class="price-symbol">¥</span>
            <span class="price-value">{{ getPrice(plan) }}</span>
            <span class="price-unit">/{{ billingCycle === 'monthly' ? '月' : '年' }}</span>
          </div>
          <div class="po-credits">{{ plan.credits }} 点数</div>
        </div>
      </div>
      <div class="recharge-action">
        <el-button
          type="primary"
          size="large"
          :loading="recharging"
          @click="recharge"
        >
          立即充值 ¥{{ getPrice(selectedPlan) }}
        </el-button>
      </div>
    </el-card>

    <!-- 订单列表 -->
    <el-card shadow="never" class="orders-card">
      <template #header>
        <span class="card-title">我的订单</span>
      </template>
      <el-table :data="orderList" stripe>
        <el-table-column prop="id" label="订单号" min-width="180" />
        <el-table-column prop="plan_name" label="套餐" width="120" />
        <el-table-column prop="period" label="周期" width="80" />
        <el-table-column prop="amount" label="金额" width="100">
          <template #default="{ row }: { row: any }">¥{{ row.amount }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }: { row: any }">
            <el-tag :type="STATUS_LABEL[row.status as OrderItem['status']].type" size="small">
              {{ STATUS_LABEL[row.status as OrderItem['status']].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }: { row: any }">
            <el-button
              v-if="row.status === 'paid' && !row.invoiced"
              type="primary"
              text
              size="small"
              @click="applyInvoice(row)"
            >
              申请发票
            </el-button>
            <el-tag v-else-if="row.invoiced" type="info" size="small">已申请发票</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="orderList.length === 0" description="暂无订单记录" />
    </el-card>
  </div>
</template>

<style scoped>
.orders-page {
  max-width: 1100px;
  margin: 0 auto;
}

.page-title {
  font-size: 20px;
  margin-bottom: 24px;
  color: var(--ai-text-primary);
}

.plan-card,
.recharge-card,
.orders-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
}

.plan-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.features {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--ai-text-regular);
}

.plan-selector {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}

.plan-option {
  flex: 1;
  border: 2px solid var(--ai-border-color);
  border-radius: 10px;
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;

  &:hover {
    border-color: var(--ai-primary-light);
  }

  &.active {
    border-color: var(--ai-primary-color);
    background: #ecf5ff;
  }

  &.recommended::before {
    content: '推荐';
    position: absolute;
    top: -10px;
    right: 12px;
    background: var(--ai-danger-color);
    color: #fff;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
  }
}

.po-name {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}

.po-price {
  margin-bottom: 8px;
}

.price-symbol {
  font-size: 16px;
  color: var(--ai-danger-color);
}

.price-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--ai-danger-color);
}

.price-unit {
  font-size: 13px;
  color: var(--ai-text-secondary);
}

.po-credits {
  font-size: 13px;
  color: var(--ai-text-regular);
}

.recharge-action {
  text-align: center;
}
</style>
