<!--
  P10 配音工作台
  功能：
    1. 角色音色映射表：角色列表 × 音色库（试听按钮）绑定
    2. 对白列表：逐句对白 + 音频播放条 + 语速/语调节点 + 单句重生成
    3. BGM 面板：推荐列表试听/选用 + 自定义上传
    4. 字幕面板：时间轴预览、样式自定义（字体/大小/颜色/描边/位置/双语）
    5. 绑定音色后可整剧批量生成
  @file views/stages/VoiceView.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useVoiceStudio } from '@/composables/useVoiceStudio'
import StageStepper from '@/components/StageStepper.vue'
import { saveSubtitleSelection } from '@/api/generate'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => route.params.id as string)

/** 当前激活的 Tab */
const activeTab = ref('voice')

/** 配音核心逻辑（音色库 / 角色绑定 / 对白生成，组合式函数封装） */
const {
  loading,
  generating,
  characters,
  voiceLibrary,
  selectedVoiceId,
  voiceMapping,
  dialogues,
  allBound,
  fetchVoices,
  fetchData,
  previewVoice,
  bindVoice,
  handleBatchGenerate,
  handleRegenerate,
  toggleSubtitle,
} = useVoiceStudio(projectId)

/** BGM 推荐列表 */
const bgmList = ref([
  { id: 'b1', name: '温馨日常', url: '/static/bgm/warm.mp3', selected: false },
  { id: 'b2', name: '紧张悬疑', url: '/static/bgm/tense.mp3', selected: false },
  { id: 'b3', name: '激昂热血', url: '/static/bgm/epic.mp3', selected: false },
  { id: 'b4', name: '伤感抒情', url: '/static/bgm/sad.mp3', selected: false },
])

let bgmAudio: HTMLAudioElement | null = null
function previewBgm(bgm: { name: string; url: string }): void {
  if (!bgm.url) {
    ElMessage.warning(`「${bgm.name}」暂无音频，请上传自定义 BGM`)
    return
  }
  if (bgmAudio) { bgmAudio.pause(); bgmAudio = null }
  bgmAudio = new Audio(bgm.url)
  bgmAudio.play().catch(() => ElMessage.warning('浏览器阻止了自动播放'))
}

/** 字幕样式 */
const subtitleStyle = reactive({
  fontFamily: '思源黑体',
  fontSize: 24,
  color: '#ffffff',
  strokeColor: '#000000',
  strokeWidth: 2,
  position: 'bottom' as 'top' | 'center' | 'bottom',
  bilingual: false,
})

/**
 * 选用 BGM
 * @param bgm - BGM 对象
 */
function selectBgm(bgm: { id: string; selected: boolean }): void {
  bgmList.value.forEach((b) => (b.selected = false))
  bgm.selected = true
  ElMessage.success('BGM 已选用')
}

/**
 * 进入合成阶段：先保存勾选的字幕，再跳转
 */
async function goComposeStage(): Promise<void> {
  try {
    const texts = dialogues.value.filter((d) => d.useForSubtitle).map((d) => d.text)
    await saveSubtitleSelection(projectId.value, texts)
  } catch (e) {
    console.warn('字幕保存失败，使用默认字幕', e)
  }
  router.push(`/project/${projectId.value}/compose`)
}

onMounted(() => {
  fetchVoices()
  fetchData()
})
</script>

<template>
  <div class="voice-view" v-loading="loading">
    <div class="page-header">
      <div class="page-title-group">
        <el-button text @click="$router.push(`/project/${projectId}/video`)" class="nav-arrow">
          <el-icon><ArrowLeft /></el-icon> 视频生成
        </el-button>
        <h1 class="page-title">配音工作台</h1>
        <el-button text type="primary" @click="goComposeStage" class="nav-arrow">
          后期合成 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
      <el-button type="primary" size="large" @click="goComposeStage">
        进入合成阶段
        <el-icon class="el-icon--right"><ArrowRight /></el-icon>
      </el-button>
    </div>
    <StageStepper current-stage="generate" />

    <el-tabs v-model="activeTab">
      <!-- 音色映射 -->
      <el-tab-pane label="角色音色" name="voice">
        <el-card shadow="never">
          <el-table :data="characters" border stripe>
            <el-table-column label="角色" width="160">
              <template #default="{ row }">
                <div class="char-cell">
                  <el-avatar :size="36" :src="row.image_url">
                    {{ row.name.charAt(0) }}
                  </el-avatar>
                  <span class="char-name">{{ row.name }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="绑定音色">
              <template #default="{ row }">
                <el-select
                  v-model="voiceMapping[row.id]"
                  placeholder="请选择音色"
                  style="width: 240px"
                  clearable
                  @change="(v) => bindVoice(row.id, v)"
                >
                  <el-option
                    v-for="v in voiceLibrary"
                    :key="v.voice_id"
                    :label="`${v.name}（${v.style}）`"
                    :value="v.voice_id"
                  >
                    <span>{{ v.name }}（{{ v.style }}）</span>
                    <el-tag size="small" type="info" style="margin-left: 8px">{{ v.provider }}</el-tag>
                  </el-option>
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button
                  v-if="voiceMapping[row.id]"
                  size="small"
                  @click="previewVoice(voiceMapping[row.id])"
                >
                  <el-icon><Microphone /></el-icon>
                  试听
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="voice-hint" v-if="!allBound">
            <el-alert type="warning" :closable="false" show-icon>
              请为所有角色绑定音色后再进行批量生成
            </el-alert>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 对白列表 -->
      <el-tab-pane label="对白列表" name="dialogue">
        <div class="dialogue-toolbar">
          <div class="voice-select-bar">
            <span class="voice-select-label">默认音色</span>
            <el-select
              v-model="selectedVoiceId"
              placeholder="请选择默认音色"
              style="width: 220px"
              clearable
            >
              <el-option
                v-for="v in voiceLibrary"
                :key="v.voice_id"
                :label="`${v.name}（${v.style}·${v.provider}）`"
                :value="v.voice_id"
              />
            </el-select>
          </div>
          <el-button type="primary" :loading="generating" :disabled="!allBound" @click="handleBatchGenerate">
            <el-icon><Microphone /></el-icon>
            批量生成配音
          </el-button>
        </div>
        <el-empty v-if="dialogues.length === 0" description="暂无对白" />
        <div v-else class="dialogue-list">
          <el-card v-for="d in dialogues" :key="d.seq" class="dialogue-card" shadow="never">
            <div class="dialogue-header">
              <el-tag size="small" type="primary">镜头#{{ d.shotSeq }}</el-tag>
              <span class="dialogue-char">{{ d.character }}</span>
              <el-checkbox v-model="d.useForSubtitle" size="small" @change="toggleSubtitle(d)">字幕</el-checkbox>
              <el-tag v-if="d.duration" size="small" type="info">时长 {{ d.duration }}s</el-tag>
              <el-tag :type="d.status === 'done' ? 'success' : d.status === 'failed' ? 'danger' : d.status === 'generating' ? 'warning' : 'info'" size="small">
                {{ d.status === 'done' ? '已生成' : d.status === 'failed' ? '失败' : d.status === 'generating' ? '生成中' : '待生成' }}
              </el-tag>
            </div>
            <div class="dialogue-text">{{ d.text }}</div>
            <div class="dialogue-controls">
              <audio v-if="d.audioUrl" :src="d.audioUrl" controls style="flex: 1; height: 36px" />
              <div v-else class="audio-placeholder">
                <el-icon><Headset /></el-icon>
                <span>暂无音频</span>
              </div>
              <div class="param-sliders">
                <span>语速</span>
                <el-slider v-model="d.speed" :min="0.5" :max="2" :step="0.1" style="width: 100px" />
                <span>语调</span>
                <el-slider v-model="d.pitch" :min="0.5" :max="2" :step="0.1" style="width: 100px" />
              </div>
              <el-button size="small" @click="handleRegenerate(d)">
                <el-icon><Refresh /></el-icon>
                重生成
              </el-button>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- BGM -->
      <el-tab-pane label="背景音乐" name="bgm">
        <el-card shadow="never">
          <div class="bgm-grid">
            <div v-for="bgm in bgmList" :key="bgm.id" class="bgm-item" :class="{ selected: bgm.selected }">
              <div class="bgm-icon">
                <el-icon :size="32"><Music /></el-icon>
              </div>
              <div class="bgm-name">{{ bgm.name }}</div>
              <div class="bgm-actions">
                <el-button size="small" text @click="previewBgm(bgm)">
                  <el-icon><VideoPlay /></el-icon>
                  试听
                </el-button>
                <el-button size="small" type="primary" @click="selectBgm(bgm)">
                  {{ bgm.selected ? '已选用' : '选用' }}
                </el-button>
              </div>
            </div>
          </div>
          <el-divider />
          <el-upload
            drag
            action="#"
            :auto-upload="false"
            accept="audio/*"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">上传自定义 BGM（拖拽音频文件到此处）</div>
          </el-upload>
        </el-card>
      </el-tab-pane>

      <!-- 字幕 -->
      <el-tab-pane label="字幕样式" name="subtitle">
        <el-card shadow="never">
          <el-form label-width="100px" style="max-width: 500px">
            <el-form-item label="字体">
              <el-select v-model="subtitleStyle.fontFamily">
                <el-option label="思源黑体" value="思源黑体" />
                <el-option label="微软雅黑" value="微软雅黑" />
                <el-option label="宋体" value="宋体" />
                <el-option label="楷体" value="楷体" />
              </el-select>
            </el-form-item>
            <el-form-item label="字号">
              <el-slider v-model="subtitleStyle.fontSize" :min="12" :max="72" show-input />
            </el-form-item>
            <el-form-item label="字体颜色">
              <el-color-picker v-model="subtitleStyle.color" />
            </el-form-item>
            <el-form-item label="描边颜色">
              <el-color-picker v-model="subtitleStyle.strokeColor" />
            </el-form-item>
            <el-form-item label="描边宽度">
              <el-slider v-model="subtitleStyle.strokeWidth" :min="0" :max="8" show-input />
            </el-form-item>
            <el-form-item label="位置">
              <el-radio-group v-model="subtitleStyle.position">
                <el-radio-button label="top">顶部</el-radio-button>
                <el-radio-button label="center">居中</el-radio-button>
                <el-radio-button label="bottom">底部</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="双语字幕">
              <el-switch v-model="subtitleStyle.bilingual" />
            </el-form-item>
          </el-form>
          <el-divider content-position="left">预览</el-divider>
          <div class="subtitle-preview">
            <div
              class="preview-text"
              :style="{
                fontFamily: subtitleStyle.fontFamily,
                fontSize: subtitleStyle.fontSize + 'px',
                color: subtitleStyle.color,
                textShadow: `0 0 ${subtitleStyle.strokeWidth}px ${subtitleStyle.strokeColor}`,
              }"
            >
              这是字幕预览文本
            </div>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.voice-view {
  min-height: 100%;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-arrow {
  font-size: 14px;
}

.page-title {
  font-size: 22px;
  margin: 0;
}

.char-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.char-name {
  font-weight: 500;
}

.voice-hint {
  margin-top: 12px;
}

.dialogue-toolbar {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 16px;
}

.voice-select-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.voice-select-label {
  font-size: 13px;
  color: var(--ai-text-regular);
}

.dialogue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dialogue-card {
  border-radius: 8px;
}

.dialogue-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.dialogue-char {
  font-weight: 600;
  color: var(--ai-primary-color);
}

.dialogue-text {
  font-size: 15px;
  line-height: 1.6;
  margin-bottom: 10px;
  color: var(--ai-text-primary);
}

.dialogue-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.audio-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ai-text-placeholder);
  padding: 8px 12px;
  background: var(--ai-bg-color);
  border-radius: 6px;
}

.param-sliders {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ai-text-regular);
}

.bgm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.bgm-item {
  padding: 16px;
  border: 2px solid var(--ai-border-color);
  border-radius: 8px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;

  &:hover {
    border-color: var(--ai-primary-light);
  }

  &.selected {
    border-color: var(--ai-primary-color);
    background: rgba(64, 158, 255, 0.05);
  }
}

.bgm-icon {
  color: var(--ai-primary-color);
  margin-bottom: 8px;
}

.bgm-name {
  font-weight: 500;
  margin-bottom: 10px;
}

.bgm-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
}

.subtitle-preview {
  height: 120px;
  background: #333;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-text {
  font-weight: bold;
}
</style>
