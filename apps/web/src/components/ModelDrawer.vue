<!--
  C03 模型配置抽屉
  右侧滑出抽屉，按能力（文本/图像/视频/TTS）四分组展示模型，点选即切换项目模型
  展示价格/速度标签，未配置 API Key 的模型提供引导入口，显示成本预估
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { Model } from '@/types'
import { listModels, setProjectModel } from '@/api/models'
import { useProjectStore } from '@/stores/project'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()

/** 抽屉是否打开 */
const drawerVisible = ref(false)
/** 模型列表 */
const models = ref<Model[]>([])
/** 加载态 */
const loading = ref(false)
/** 切换中 */
const switching = ref(false)

/** 能力分组定义：key 为 Model.type，label 为中文名 */
const GROUPS: Array<{ key: Model['type']; label: string; icon: string }> = [
  { key: 'llm', label: '文本（LLM）', icon: 'Document' },
  { key: 'image', label: '图像', icon: 'Picture' },
  { key: 'video', label: '视频', icon: 'VideoPlay' },
  { key: 'audio', label: '语音（TTS）', icon: 'Microphone' },
]

/** 各厂商默认价格（元/千 token 或 元/次）与速度标签 */
const PROVIDER_META: Record<string, { price: string; speed: '快' | '中' | '慢' }> = {
  openai: { price: '¥0.02/千tokens', speed: '快' },
  anthropic: { price: '¥0.08/千tokens', speed: '中' },
  qwen: { price: '¥0.008/千tokens', speed: '快' },
  deepseek: { price: '¥0.002/千tokens', speed: '快' },
  moonshot: { price: '¥0.012/千tokens', speed: '中' },
  stability: { price: '¥0.1/张', speed: '中' },
  midjourney: { price: '¥0.3/张', speed: '慢' },
  runway: { price: '¥2/秒', speed: '慢' },
  kling: { price: '¥1.5/秒', speed: '中' },
  sambert: { price: '¥0.05/次', speed: '快' },
  fishaudio: { price: '¥0.08/次', speed: '快' },
}

/**
 * 获取当前项目 ID（优先路由参数，其次 store；store 中 id 为 number，统一转为字符串）
 * @returns 项目 ID，不存在时返回空字符串
 */
const currentProjectId = computed<string>(() => {
  return (
    (route.params.id as string) || String(projectStore.currentProject?.id ?? '')
  )
})

/**
 * 按能力分组后的模型列表
 * @returns 分组后的模型数据
 */
const groupedModels = computed(() => {
  return GROUPS.map((g) => ({
    ...g,
    list: models.value.filter((m) => m.type === g.key),
  })).filter((g) => g.list.length > 0)
})

/**
 * 获取厂商价格信息
 * @param provider - 厂商名称
 * @returns 价格与速度标签
 */
function getProviderMeta(provider: string) {
  return PROVIDER_META[provider.toLowerCase()] || { price: '价格未知', speed: '中' as const }
}

/**
 * 计算粗略成本预估（单次调用）
 * @param model - 模型对象
 * @returns 预估成本描述
 */
function estimateCost(model: Model): string {
  const meta = getProviderMeta(model.provider)
  if (model.type === 'llm') return `约 ${meta.price}`
  if (model.type === 'image') return `约 ${meta.price}`
  if (model.type === 'video') return `约 ${meta.price}`
  if (model.type === 'audio') return `约 ${meta.price}`
  return '—'
}

/**
 * 判断厂商是否已配置 API Key（基于后端返回的 key_configured 标记）
 * @param provider - 厂商名称
 * @returns 是否已配置
 */
function isKeyConfigured(provider: string): boolean {
  return models.value.some(
    (m) => m.provider.toLowerCase() === provider.toLowerCase() && m.key_configured,
  )
}

/**
 * 拉取模型列表
 */
async function fetchModels(): Promise<void> {
  loading.value = true
  try {
    const res = await listModels({
      project_id: currentProjectId.value || undefined,
    })
    models.value = res
  } catch (e) {
    console.error('拉取模型列表失败', e)
  } finally {
    loading.value = false
  }
}

/**
 * 切换项目模型
 * @param model - 目标模型
 */
async function handleSelect(model: Model): Promise<void> {
  if (!currentProjectId.value) {
    ElMessage.warning('请先打开一个项目再切换模型')
    return
  }
  if (!isKeyConfigured(model.provider)) {
    ElMessage.warning(`请先配置 ${model.provider} 的 API Key`)
    return
  }
  switching.value = true
  try {
    await setProjectModel(currentProjectId.value, { type: model.type, model_id: model.id })
    // 本地更新 is_default 状态
    models.value.forEach((m) => {
      m.is_default = m.type === model.type ? m.id === model.id : m.is_default
    })
    ElMessage.success(`已切换为 ${model.name}`)
  } catch (e) {
    ElMessage.error('切换模型失败')
  } finally {
    switching.value = false
  }
}

/**
 * 跳转到个人中心 API Key 管理页
 */
function goKeyManage(): void {
  router.push('/profile/apikey')
  drawerVisible.value = false
}

/**
 * 打开抽屉
 */
function openDrawer(): void {
  drawerVisible.value = true
  // 每次打开都刷新，确保新配置的 Key / 模型立即生效
  fetchModels()
}

/** 暴露 openDrawer 供父组件通过 ref 调用 */
defineExpose({ openDrawer })

onMounted(() => {
  fetchModels()
})
</script>

<template>
  <!-- 模型配置抽屉：由父组件通过 ref.openDrawer() 触发打开 -->
  <el-drawer
    v-model="drawerVisible"
    title="模型配置"
    direction="rtl"
    size="560px"
    destroy-on-close
  >
    <div class="model-drawer">
      <!-- 顶部操作栏 -->
      <div class="drawer-header">
        <el-alert
          v-if="!currentProjectId"
          title="当前未在项目中，切换模型需要打开一个项目"
          type="info"
          show-icon
          :closable="false"
        />
        <el-button type="primary" link @click="goKeyManage">
          <el-icon><Key /></el-icon>
          管理 API Key
        </el-button>
      </div>

      <el-skeleton v-if="loading" :rows="8" animated />

      <template v-else>
        <el-empty v-if="groupedModels.length === 0" description="暂无可用模型" />

        <div v-else class="groups">
          <div v-for="group in groupedModels" :key="group.key" class="group">
            <div class="group-title">
              <el-icon><component :is="group.icon" /></el-icon>
              {{ group.label }}
              <span class="group-count">（{{ group.list.length }} 个可用）</span>
            </div>

            <div class="model-list">
              <div
                v-for="model in group.list"
                :key="model.id"
                class="model-card"
                :class="{ active: model.is_default, disabled: !isKeyConfigured(model.provider) }"
                @click="handleSelect(model)"
              >
                <div class="model-card-header">
                  <span class="model-name">{{ model.name }}</span>
                  <el-tag
                    v-if="model.is_default"
                    type="success"
                    size="small"
                    effect="dark"
                  >当前</el-tag>
                  <el-tag
                    v-if="!isKeyConfigured(model.provider)"
                    type="warning"
                    size="small"
                    effect="plain"
                  >未配 Key</el-tag>
                </div>

                <div class="model-card-body">
                  <span class="model-provider">厂商：{{ model.provider }}</span>
                  <el-tag size="small" type="info" effect="plain">
                    {{ getProviderMeta(model.provider).price }}
                  </el-tag>
                  <el-tag size="small" type="success" effect="plain">
                    速度：{{ getProviderMeta(model.provider).speed }}
                  </el-tag>
                </div>

                <div class="model-card-footer">
                  <span class="cost-label">单次预估：</span>
                  <span class="cost-value">{{ estimateCost(model) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.model-trigger {
  /* 触发按钮样式由父组件布局决定 */
}

.model-drawer {
  height: 100%;
  overflow-y: auto;
  padding: 0 4px;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  gap: 12px;
}

.groups {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--ai-text-primary);
  margin-bottom: 12px;
}

.group-count {
  font-size: 12px;
  font-weight: normal;
  color: var(--ai-text-secondary);
}

.model-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.model-card {
  border: 1px solid var(--ai-border-color);
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--ai-bg-white);

  &:hover {
    border-color: var(--ai-primary-color);
    box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
  }

  &.active {
    border-color: var(--ai-primary-color);
    background: #ecf5ff;
  }

  &.disabled {
    opacity: 0.7;
  }
}

.model-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.model-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--ai-text-primary);
}

.model-card-body {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 12px;
}

.model-provider {
  color: var(--ai-text-regular);
}

.model-card-footer {
  font-size: 12px;
  color: var(--ai-text-secondary);
  border-top: 1px dashed var(--ai-border-color);
  padding-top: 8px;
}

.cost-value {
  color: var(--ai-danger-color);
  font-weight: 600;
}
</style>
