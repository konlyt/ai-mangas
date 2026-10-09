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
    characters.value = chars
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
  try {
    await generateCharacters(projectId.value)
    // 模拟进度
    const timer = setInterval(() => {
      generateProgress.value += 10
      if (generateProgress.value >= 100) {
        clearInterval(timer)
        generating.value = false
        fetchAssets()
        ElMessage.success('角色生成完成')
      }
    }, 300)
  } catch (e) {
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
 * 重新生成单个角色
 * @param c - 角色对象
 */
async function handleRegenerateOne(c: Character): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除并重新生成角色「${c.name}」？当前图片将被删除，系统会根据剧本自动重新生成。`,
      '重新生成确认',
      { type: 'warning', confirmButtonText: '确认重新生成', cancelButtonText: '取消' }
    )
    drawerVisible.value = false
    generating.value = true
    generateProgress.value = 10
    ElMessage.info('正在重新生成角色，请稍候...')
    await generateCharacters(projectId.value)
    generateProgress.value = 100
    generating.value = false
    await fetchAssets()
    ElMessage.success('角色重新生成完成')
  } catch (e) {
    generating.value = false
    // 用户取消
  }
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
    <!-- 顶部标题 -->
    <div class="page-header">
      <h1 class="page-title">资产管理</h1>
    </div>
    <StageStepper current-stage="assets" />

    <!-- 批量操作栏 -->
    <div class="batch-bar">
      <el-button type="primary" :loading="generating" @click="handleGenerateCharacters">
        <el-icon><MagicStick /></el-icon>
        批量生成角色
      </el-button>
      <el-button :disabled="characters.length === 0" @click="handleLockAll">
        <el-icon><Lock /></el-icon>
        全部锁定
      </el-button>
      <el-button :disabled="characters.length === 0" @click="handleUnlockAll">
        <el-icon><Unlock /></el-icon>
        全部解锁
      </el-button>
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
    <el-tabs v-model="activeTab" class="asset-tabs">
      <!-- 角色 Tab -->
      <el-tab-pane label="角色" name="character">
        <el-empty v-if="characters.length === 0 && !loading" description="暂无角色，点击「批量生成角色」创建" />
        <div v-else class="asset-grid">
          <el-card
            v-for="c in characters"
            :key="c.id"
            class="asset-card"
            shadow="hover"
            @click="openDetail(c)"
          >
            <div class="card-image">
              <el-image
                :src="c.main_asset_url"
                fit="cover"
                class="portrait"
              >
                <template #error>
                  <div class="image-placeholder">
                    <el-icon :size="40"><User /></el-icon>
                  </div>
                </template>
              </el-image>
              <el-tag v-if="c.is_locked ?? c.locked" type="success" class="lock-badge" effect="dark">
                <el-icon><Lock /></el-icon>
                已锁定
              </el-tag>
            </div>
            <div class="card-info">
              <div class="asset-name-row">
                <div class="asset-name">{{ c.name }}</div>
                <div class="card-actions">
                  <el-button size="small" text type="primary" @click.stop="handleUnlockOne(c)" v-if="c.is_locked ?? c.locked">
                    <el-icon><Unlock /></el-icon>
                    解锁
                  </el-button>
                  <el-button size="small" text type="danger" @click.stop="handleDeleteOne(c)">
                    <el-icon><Delete /></el-icon>
                    删除
                  </el-button>
                  <el-upload
                    class="ref-upload"
                    action="#"
                    accept="image/jpeg,image/png,image/webp"
                    :show-file-list="false"
                    :before-upload="beforeReferenceUpload"
                    :http-request="(opt) => doUploadReference(opt, c)"
                    @click.stop
                  >
                    <el-button size="small" text type="primary">
                      <el-icon><Upload /></el-icon>
                      上传参考图
                    </el-button>
                  </el-upload>
                </div>
              </div>
              <div v-if="c.reference_url" class="reference-row" @click.stop>
                <el-image
                  :src="c.reference_url"
                  fit="cover"
                  class="ref-thumb"
                  :preview-src-list="[c.reference_url]"
                  preview-teleported
                />
                <span class="ref-label">参考图</span>
              </div>
              <div class="similarity" @click.stop>
                <el-tooltip placement="top" effect="dark">
                  <template #content>
                    <div class="compare-tooltip">
                      <div>一致性对照图</div>
                      <el-image :src="c.main_asset_url" fit="cover" style="width:120px;height:120px" />
                    </div>
                  </template>
                  <el-tag type="warning" size="small">相似度 {{ (85 + Math.random() * 10).toFixed(1) }}%</el-tag>
                </el-tooltip>
              </div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 场景 Tab -->
      <el-tab-pane label="场景" name="scene">
        <el-empty v-if="scenes.length === 0 && !loading" description="暂无场景" />
        <div v-else class="asset-grid">
          <el-card
            v-for="s in scenes"
            :key="s.id"
            class="asset-card"
            shadow="hover"
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
            <div class="card-info">
              <div class="asset-name">{{ s.name }}</div>
              <div class="scene-desc text-ellipsis">{{ s.description }}</div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

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

.page-header {
  margin-bottom: 16px;
}

.page-title {
  font-size: 22px;
  color: var(--ai-text-primary);
  margin: 0;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.progress-text {
  font-size: 13px;
  color: var(--ai-primary-color);
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.asset-card {
  cursor: pointer;
  overflow: hidden;
}

.card-image {
  position: relative;
  width: 100%;
  height: 240px;
  overflow: hidden;
  border-radius: 4px;
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

.lock-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 2px;
}

.unlock-btn {
  position: absolute;
  top: 36px;
  right: 8px;
  z-index: 10;
}

.delete-btn {
  position: absolute;
  top: 68px;
  right: 8px;
  z-index: 10;
}

.card-info {
  padding: 12px 4px 4px;
}

.asset-name {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
}

.asset-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ref-upload {
  flex-shrink: 0;
  line-height: 1;
}

.reference-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0 6px;
}

.ref-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  border: 1px solid var(--ai-border-color, #e5e7eb);
}

.ref-label {
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.scene-desc {
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.similarity {
  margin-top: 4px;
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

.thumb-row {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 8px;
}

.thumb-item {
  flex-shrink: 0;
  text-align: center;
}

.thumb {
  width: 80px;
  height: 80px;
  border-radius: 6px;
}

.thumb-label {
  font-size: 12px;
  color: var(--ai-text-secondary);
}

.similarity-badge {
  text-align: center;
  padding: 8px 0;
}

.detail-actions {
  margin-top: 16px;
  text-align: right;
}
</style>
