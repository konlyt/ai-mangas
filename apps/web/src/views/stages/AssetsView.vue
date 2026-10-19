<!--
  P06 资产管理页
  功能：
    1. 资产画廊：角色 Tab / 场景 Tab
    2. 角色卡片：主定妆照 + 姓名 + 锁定徽标
    3. 单资产详情抽屉：大图预览、多角度缩略图、视觉提示词编辑、相似度分数徽章
    4. 批量操作栏：批量生成、全部锁定
    5. 生成进度条
    6. 底部：锁定全部资产进入分镜阶段
  @file views/stages/AssetsView.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRawFile, UploadRequestOptions } from 'element-plus'
import type { Character, Scene } from '@/types'
import {
  generateCharacters,
  getCharacters,
  lockCharacter,
  unlockCharacter,
  deleteCharacter,
  getScenes,
  uploadReference,
  regenerateCharacter,
  type CharacterWithReference,
} from '@/api/assets'
import { resumeGraph } from '@/api/graph'
import StageStepper from '@/components/StageStepper.vue'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.id as string)

/** 参考图允许的 MIME 类型 */
const ALLOWED_REFERENCE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
/** 参考图大小上限：5MB */
const REFERENCE_MAX_SIZE = 5 * 1024 * 1024

/** 当前激活的 Tab */
const activeTab = ref<'character' | 'scene'>('character')
/** 加载状态 */
const loading = ref(false)
/** 生成中状态 */
const generating = ref(false)
/** 生成进度百分比 */
const generateProgress = ref(0)

/** 角色列表（含后端返回的参考图 URL） */
const characters = ref<CharacterWithReference[]>([])
/** 场景列表 */
const scenes = ref<Scene[]>([])

/** 详情抽屉 */
const drawerVisible = ref(false)
/** 当前查看的资产 */
const currentAsset = ref<Character | Scene | null>(null)
/** 编辑中的视觉提示词 */
const editPrompt = ref('')

/** 选中的资产 ID 列表（批量操作） */
const selectedIds = ref<string[]>([])

/**
 * 是否所有角色都已锁定
 */
const allLocked = computed(() => characters.value.length > 0 && characters.value.every((c) => c.is_locked ?? c.locked))

/**
 * 获取角色与场景数据
 */
async function fetchAssets(): Promise<void> {
  loading.value = true
  try {
    const [chars, scs] = await Promise.all([getCharacters(projectId.value), getScenes(projectId.value)])
    // 按 name 去重：同名角色只保留最新的（id 最大的）
    const seen = new Map<string, any>()
    for (const c of chars) {
      const key = c.name
      const existing = seen.get(key)
      if (!existing || c.id > existing.id) {
        seen.set(key, c)
      }
    }
    characters.value = Array.from(seen.values())
    scenes.value = scs
  } catch (e) {
    ElMessage.error('获取资产列表失败')
  } finally {
    loading.value = false
  }
}

/**
 * 批量生成角色
 */
async function handleGenerateCharacters(): Promise<void> {
  generating.value = true
  generateProgress.value = 0
  ElMessage.info('正在生成角色，请稍候...')
  
  // 立即启动模拟进度（不等接口返回）
  const timer = setInterval(() => {
    if (generateProgress.value < 90) {
      generateProgress.value += Math.random() * 5 + 2
    }
  }, 500)
  
  try {
    await generateCharacters(projectId.value)
    clearInterval(timer)
    generateProgress.value = 100
    generating.value = false
    await fetchAssets()
    ElMessage.success('角色生成完成')
  } catch (e) {
    clearInterval(timer)
    generating.value = false
    ElMessage.error('角色生成失败，请重试')
  }
}

/**
 * 锁定单个角色
 * @param c - 角色对象
 */
async function handleLock(c: Character): Promise<void> {
  try {
    const updated = await lockCharacter(projectId.value, c.id)
    const idx = characters.value.findIndex((item) => item.id === c.id)
    if (idx !== -1) characters.value[idx] = updated
    ElMessage.success(`${c.name} 已锁定`)
  } catch (e) {
    ElMessage.error('锁定失败')
  }
}

/**
 * 全部锁定角色
 */
async function handleLockAll(): Promise<void> {
  try {
    await ElMessageBox.confirm('确认锁定全部角色？锁定后不可重新生成。', '全部锁定', {
      type: 'warning',
    })
    for (const c of characters.value) {
      if (!(c.is_locked ?? c.locked)) {
        await lockCharacter(projectId.value, c.id)
      }
    }
    await fetchAssets()
    ElMessage.success('全部角色已锁定')
  } catch (e) {
    // 用户取消
  }
}

/**
 * 全部解锁角色
 */
async function handleUnlockAll(): Promise<void> {
  try {
    await ElMessageBox.confirm('确认解锁全部角色？解锁后可以重新生成。', '全部解锁', {
      type: 'info',
    })
    for (const c of characters.value) {
      if (c.is_locked ?? c.locked) {
        await unlockCharacter(projectId.value, String(c.id))
      }
    }
    await fetchAssets()
    ElMessage.success('全部角色已解锁')
  } catch (e) {
    // 用户取消
  }
}

/**
 * 解锁单个角色
 * @param c - 角色对象
 */
async function handleUnlockOne(c: Character): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认解锁角色「${c.name}」？`, '解锁确认', {
      type: 'info',
    })
    await unlockCharacter(projectId.value, String(c.id))
    await fetchAssets()
    ElMessage.success(`已解锁「${c.name}」`)
  } catch (e) {
    // 用户取消
  }
}

/**
 * 删除单个角色
 * @param c - 角色对象
 */
async function handleDeleteOne(c: Character): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除角色「${c.name}」？删除后不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
    await deleteCharacter(projectId.value, String(c.id))
    await fetchAssets()
    ElMessage.success(`已删除「${c.name}」`)
  } catch (e) {
    // 用户取消
  }
}

/**
 * 重新生成单个角色（换一张）
 * @param c - 角色对象
 */
async function handleRegenerateOne(c: Character): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认重新生成角色「${c.name}」？当前图片将被替换，其他角色不受影响。`,
      '换一张确认',
      { type: 'warning', confirmButtonText: '确认换一张', cancelButtonText: '取消' }
    )
    drawerVisible.value = false
    generating.value = true
    generateProgress.value = 30
    ElMessage.info(`正在重新生成「${c.name}」，请稍候...`)
    const updated = await regenerateCharacter(projectId.value, String(c.id))
    generateProgress.value = 100
    generating.value = false
    // 直接用接口返回的数据更新列表，而不是重新拉取
    const idx = characters.value.findIndex(ch => ch.id === c.id)
    if (idx >= 0) {
      characters.value[idx] = { ...characters.value[idx], ...updated }
      console.log('已更新角色:', c.name, '新URL:', updated.main_asset_url)
    }
    // 同时后台重新拉取，确保数据一致
    fetchAssets()
    ElMessage.success(`「${c.name}」已重新生成`)
  } catch (e) {
    generating.value = false
    console.error('重新生成失败:', e)
  }
}

/**
 * 获取角色主图 URL（优先从 variants 里找 front 类型，防缓存）
 */
function getCharacterImage(c: any): string {
  // 优先从 variants 里找 front 类型
  if (c.variants && c.variants.length > 0) {
    const front = c.variants.find((v: any) => v.variant_type === 'front' && v.image_url)
    if (front) {
      return front.image_url + (front.image_url.includes('?') ? '&' : '?') + 't=' + Date.now()
    }
  }
  //  fallback 到 main_asset_url
  if (c.main_asset_url) {
    return c.main_asset_url + (c.main_asset_url.includes('?') ? '&' : '?') + 't=' + Date.now()
  }
  return ''
}

/**
 * 打开资产详情抽屉
 * @param asset - 资产对象
 */
function openDetail(asset: Character | Scene): void {
  currentAsset.value = asset
  editPrompt.value = (asset as Character).description || (asset as Scene).description || ''
  drawerVisible.value = true
}

/**
 * 参考图上传前校验：仅允许 jpg/png/webp，且大小 ≤5MB
 * @param file - 待上传的原始文件对象
 * @returns 校验通过返回 true，否则返回 false 阻止上传
 */
function beforeReferenceUpload(file: UploadRawFile): boolean {
  if (!ALLOWED_REFERENCE_TYPES.includes(file.type)) {
    ElMessage.error('仅支持 jpg/png/webp 格式图片')
    return false
  }
  if (file.size > REFERENCE_MAX_SIZE) {
    ElMessage.error('图片大小不能超过 5MB')
    return false
  }
  return true
}

/**
 * 执行参考图上传，成功后把返回 URL 写回角色数据以显示缩略图
 * @param options - el-upload 自定义上传选项（含 file 文件对象）
 * @param c - 目标角色对象
 */
async function doUploadReference(
  options: UploadRequestOptions,
  c: CharacterWithReference
): Promise<void> {
  try {
    const res = await uploadReference(projectId.value, c.id, options.file)
    c.reference_url = res.url
    ElMessage.success(`${c.name} 参考图上传成功`)
  } catch (e) {
    // 错误提示由 request 响应拦截器统一弹出
  }
}

/**
 * 保存提示词编辑
 */
function handleSavePrompt(): void {
  if (currentAsset.value) {
    ;(currentAsset.value as Character).description = editPrompt.value
    ElMessage.success('提示词已保存')
  }
}

/**
 * 确认全部资产锁定，进入分镜阶段
 */
async function handleConfirm(): Promise<void> {
  if (!allLocked.value) {
    ElMessage.warning('请先锁定全部角色')
    return
  }
  ElMessage.success('资产已确认，进入分镜阶段')
  router.push(`/project/${projectId.value}/storyboard`)
}

onMounted(() => {
  fetchAssets()
})
</script>

<template>
  <div class="assets-view" v-loading="loading">
    <StageStepper current-stage="assets" />

    <!-- 批量操作栏 -->
    <div class="batch-bar">
      <button class="btn-gradient btn-generate" :disabled="generating" @click="handleGenerateCharacters">
        <el-icon><MagicStick /></el-icon>
        批量生成角色
      </button>
      <button class="btn-white" :disabled="characters.length === 0" @click="handleLockAll">
        <el-icon><Lock /></el-icon>
        全部锁定
      </button>
      <button class="btn-white" :disabled="characters.length === 0" @click="handleUnlockAll">
        <el-icon><Unlock /></el-icon>
        全部解锁
      </button>
      <span v-if="generating" class="progress-text">
        生成中 {{ generateProgress }}%
      </span>
    </div>

    <!-- 生成进度条 -->
    <el-progress
      v-if="generating"
      :percentage="generateProgress"
      :stroke-width="8"
      style="margin-bottom: 16px"
    />

    <!-- Tab 切换 -->
    <div class="custom-tabs">
      <div
        class="tab-item"
        :class="{ active: activeTab === 'character' }"
        @click="activeTab = 'character'"
      >
        角色
      </div>
      <div
        class="tab-item"
        :class="{ active: activeTab === 'scene' }"
        @click="activeTab = 'scene'"
      >
        场景
      </div>
    </div>

    <!-- 角色 Tab 内容 -->
    <div v-if="activeTab === 'character'">
      <el-empty v-if="characters.length === 0 && !loading" description="暂无角色，点击「批量生成角色」创建" />
      <div v-else class="asset-grid">
        <div
          v-for="c in characters"
          :key="c.id"
          class="asset-card"
          @click="openDetail(c)"
        >
          <div class="card-image">
            <el-image
              :src="getCharacterImage(c)"
              fit="cover"
              class="portrait"
            >
              <template #error>
                <div class="image-placeholder">
                  <el-icon :size="40"><User /></el-icon>
                </div>
              </template>
            </el-image>
            <div v-if="c.is_locked ?? c.locked" class="lock-badge">
              <el-icon><Lock /></el-icon>
              已锁定
            </div>
          </div>
          <div class="card-body">
            <div class="asset-name">{{ c.name }}</div>
            <div class="btn-row">
              <button class="btn-gradient half-btn" @click.stop="handleRegenerateOne(c)">
                <el-icon><RefreshRight /></el-icon>
                换一张
              </button>
              <el-upload
                class="half-btn ref-upload"
                action="#"
                accept="image/jpeg,image/png,image/webp"
                :show-file-list="false"
                :before-upload="beforeReferenceUpload"
                :http-request="(opt) => doUploadReference(opt, c)"
                @click.stop
              >
                <button class="btn-gradient half-btn">
                  <el-icon><Upload /></el-icon>
                  上传参考图
                </button>
              </el-upload>
            </div>
            <div class="bottom-row">
              <span class="similarity-tag">相似度 --</span>
              <div class="mini-actions">
                <span
                  v-if="c.is_locked ?? c.locked"
                  class="action-text unlock"
                  @click.stop="handleUnlockOne(c)"
                >
                  解锁
                </span>
                <span class="action-text delete" @click.stop="handleDeleteOne(c)">
                  删除
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 场景 Tab 内容 -->
    <div v-else>
      <el-empty v-if="scenes.length === 0 && !loading" description="暂无场景" />
      <div v-else class="asset-grid">
        <div
          v-for="s in scenes"
          :key="s.id"
          class="asset-card"
          @click="openDetail(s)"
        >
          <div class="card-image">
            <el-image :src="s.image_url" fit="cover" class="portrait">
              <template #error>
                <div class="image-placeholder">
                  <el-icon :size="40"><Picture /></el-icon>
                </div>
              </template>
            </el-image>
          </div>
          <div class="card-body">
            <div class="asset-name">{{ s.name }}</div>
            <div class="scene-desc text-ellipsis">{{ s.description }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部确认按钮 -->
    <div class="page-footer">
      <el-button
        type="primary"
        size="large"
        :disabled="!allLocked"
        @click="handleConfirm"
      >
        锁定全部资产，进入分镜阶段
        <el-icon class="el-icon--right"><ArrowRight /></el-icon>
      </el-button>
    </div>

    <!-- 资产详情抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="currentAsset?.name || '资产详情'"
      direction="rtl"
      size="480px"
    >
      <div v-if="currentAsset" class="detail-content">
        <el-image
          :src="currentAsset.main_asset_url || currentAsset.image_url"
          fit="contain"
          class="detail-image"
        >
          <template #error>
            <div class="image-placeholder large">
              <el-icon :size="60"><User /></el-icon>
            </div>
          </template>
        </el-image>

        <el-divider content-position="left">角色描述</el-divider>
        <p class="char-desc">{{ currentAsset.description || '暂无描述' }}</p>

        <el-divider content-position="left">视觉提示词</el-divider>
        <el-input
          v-model="editPrompt"
          type="textarea"
          :rows="5"
          placeholder="编辑视觉提示词..."
        />
        <div class="detail-actions">
          <el-button type="primary" @click="handleSavePrompt">保存提示词</el-button>
          <el-button type="danger" @click="handleRegenerateOne(currentAsset as Character)">
            <el-icon><RefreshRight /></el-icon>
            重新生成此角色
          </el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.assets-view {
  min-height: 100%;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 20px 0 16px;
}

/* 渐变按钮样式 */
.btn-gradient {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #667eea 0%, #f093fb 100%);
  color: white;
  font-size: 13px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-gradient:hover {
  opacity: 0.9;
}

.btn-gradient:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 白色按钮样式 */
.btn-white {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 16px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: white;
  color: #333;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-white:hover {
  border-color: #667eea;
  color: #667eea;
}

.btn-white:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.progress-text {
  font-size: 13px;
  color: var(--ai-primary-color);
}

/* 自定义 Tab */
.custom-tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid #e8e8e8;
  margin-bottom: 20px;
}

.tab-item {
  padding: 8px 0;
  font-size: 15px;
  color: #666;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 0.2s;
}

.tab-item.active {
  color: #667eea;
  border-bottom-color: #667eea;
  font-weight: 500;
}

/* 卡片网格 */
.asset-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 20px;
}

.asset-card {
  background: white;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.asset-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.card-image {
  position: relative;
  width: 100%;
  aspect-ratio: 4/5;
  overflow: hidden;
  background: #f5f5f5;
}

.portrait {
  width: 100%;
  height: 100%;
}

.image-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--ai-bg-color);
  color: var(--ai-text-placeholder);

  &.large {
    height: 300px;
  }
}

/* 锁定徽章 */
.lock-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #52c41a;
  color: white;
  font-size: 12px;
  border-radius: 12px;
}

/* 卡片内容区 */
.card-body {
  padding: 12px 14px 14px;
}

.asset-name {
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin-bottom: 12px;
}

/* 按钮行 */
.btn-row {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.half-btn {
  flex: 1;
}

.btn-gradient.half-btn {
  padding: 6px 8px;
  font-size: 12px;
  border-radius: 6px;
}

.ref-upload {
  flex-shrink: 0;
  line-height: 1;
}

/* 底部行 */
.bottom-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.similarity-tag {
  font-size: 12px;
  color: #999;
  background: #f5f5f5;
  padding: 2px 8px;
  border-radius: 4px;
}

.mini-actions {
  display: flex;
  gap: 12px;
}

.action-text {
  font-size: 12px;
  cursor: pointer;
}

.action-text.unlock {
  color: #fa8c16;
}

.action-text.delete {
  color: #f5222d;
}

.scene-desc {
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.page-footer {
  display: flex;
  justify-content: flex-end;
  padding: 24px 0;
}

/* 详情抽屉 */
.detail-content {
  padding: 8px;
}

.detail-image {
  width: 100%;
  height: 320px;
  border-radius: 8px;
  overflow: hidden;
}

.detail-actions {
  margin-top: 16px;
  text-align: right;
}

/* 响应式 */
@media (max-width: 1200px) {
  .asset-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 992px) {
  .asset-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .asset-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
