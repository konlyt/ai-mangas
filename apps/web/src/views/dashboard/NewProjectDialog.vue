<!--
  新建项目弹窗
  分步向导：①输入创意 → ②配置信息 → ③确认创建
  支持三种输入模式：一句话创意 / 上传 txt / 粘贴大纲
  提交后创建项目并跳转剧本页
  @file views/dashboard/NewProjectDialog.vue
-->
<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, type UploadRawFile } from 'element-plus'
import { createProject } from '@/api/projects'
import type { Project } from '@/types'

/** 组件 Props */
interface Props {
  /** 弹窗是否显示 */
  modelValue: boolean
}

const props = defineProps<Props>()

/** 事件定义 */
const emit = defineEmits<{
  /** 更新 v-model 显示状态 */
  (e: 'update:modelValue', val: boolean): void
  /** 项目创建成功，传递新创建的项目 */
  (e: 'created', project: Project): void
}>()

/** 当前步骤索引 0-2 */
const activeStep = ref(0)

/** 步骤标题列表 */
const steps = ['输入创意', '配置信息', '确认创建']

/** 输入模式类型 */
type InputMode = 'idea' | 'upload' | 'paste'

/** 输入模式：一句话创意 / 上传 txt / 粘贴大纲 */
const inputMode = ref<InputMode>('idea')

/** 表单数据 */
const form = reactive({
  /** 一句话创意 */
  idea: '',
  /** 粘贴的大纲内容 */
  outline: '',
  /** 项目标题 */
  title: '',
  /** 体裁 */
  genre: '科幻',
  /** 自定义体裁 */
  customGenre: '',
  /** 风格 */
  style: '二次元',
  /** 目标集数 */
  episodes: 1,
  /** 单集目标时长（分钟） */
  duration: 1,
  /** 输出比例 */
  ratio: '9:16',
  /** 上传的文件名 */
  fileName: '',
})

/** 提交加载状态 */
const loading = ref(false)

/** 体裁预设列表 */
const genrePresets = ['科幻', '古风', '都市', '悬疑', '热血', '奇幻', '校园']

/** 风格预设列表 */
const stylePresets = ['写实', '二次元', '赛博朋克', '水墨', '油画', '3D']

/** 输出比例选项 */
const ratioOptions = ['9:16', '16:9', '1:1']

/** 最终体裁：自定义体裁优先于预设 */
const finalGenre = computed(() => form.customGenre || form.genre)

/**
 * 关闭弹窗
 */
function closeDialog(): void {
  emit('update:modelValue', false)
}

/**
 * 下一步：校验当前步骤输入，通过则进入下一步或提交
 */
function nextStep(): void {
  // 步骤一：根据输入模式校验
  if (activeStep.value === 0) {
    if (inputMode.value === 'idea' && !form.idea.trim()) {
      ElMessage.warning('请输入一句话创意')
      return
    }
    if (inputMode.value === 'paste' && !form.outline.trim()) {
      ElMessage.warning('请粘贴大纲内容')
      return
    }
    if (inputMode.value === 'upload' && !form.fileName) {
      ElMessage.warning('请上传 txt 文件')
      return
    }
  }
  // 步骤二：标题必填
  if (activeStep.value === 1) {
    if (!form.title.trim()) {
      ElMessage.warning('请输入项目标题')
      return
    }
  }
  if (activeStep.value < 2) {
    activeStep.value++
  } else {
    submitCreate()
  }
}

/**
 * 返回上一步
 */
function prevStep(): void {
  if (activeStep.value > 0) activeStep.value--
}

/**
 * 文件上传前校验并读取内容到本地
 * @param file - 待上传的原始文件
 * @returns false 阻止自动上传，仅本地读取
 */
function beforeUpload(file: UploadRawFile): boolean {
  const isTxt = file.name?.endsWith('.txt')
  if (!isTxt) {
    ElMessage.error('仅支持上传 txt 格式文件')
    return false
  }
  form.fileName = file.name
  // 本地读取文件内容作为大纲
  const reader = new FileReader()
  reader.onload = (e) => {
    form.outline = (e.target?.result as string) || ''
  }
  reader.readAsText(file)
  return false
}

/**
 * 移除已上传文件
 */
function handleRemove(): void {
  form.fileName = ''
  form.outline = ''
}

/**
 * 提交创建项目
 * 将创意/大纲与元信息拼装为描述，调用创建接口
 */
async function submitCreate(): Promise<void> {
  loading.value = true
  try {
    const descriptionParts: string[] = []
    if (inputMode.value === 'idea' && form.idea) {
      descriptionParts.push(`创意：${form.idea}`)
    } else if (form.outline) {
      descriptionParts.push(`大纲：${form.outline}`)
    }
    descriptionParts.push(`体裁：${finalGenre.value}`)
    descriptionParts.push(`风格：${form.style}`)
    descriptionParts.push(`集数：${form.episodes}`)
    descriptionParts.push(`单集时长：${form.duration} 分钟`)
    descriptionParts.push(`输出比例：${form.ratio}`)

    const project = await createProject({
      title: form.title,
      genre: form.genre,
      style: form.style,
      aspect_ratio: form.ratio,
      raw_input: descriptionParts.join('\n'),
    })
    ElMessage.success('项目创建成功')
    emit('created', project)
    resetForm()
  } catch (err) {
    // 错误已由拦截器统一提示
    console.error('创建项目失败：', err)
  } finally {
    loading.value = false
  }
}

/**
 * 重置表单到初始状态
 */
function resetForm(): void {
  activeStep.value = 0
  inputMode.value = 'idea'
  form.idea = ''
  form.outline = ''
  form.title = ''
  form.genre = '科幻'
  form.customGenre = ''
  form.style = '二次元'
  form.episodes = 1
  form.duration = 1
  form.ratio = '9:16'
  form.fileName = ''
}

// 每次打开弹窗时重置表单
watch(
  () => props.modelValue,
  (val) => {
    if (val) resetForm()
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="新建漫剧项目"
    width="640px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- 步骤条 -->
    <el-steps :active="activeStep" align-center finish-status="success" class="dialog-steps">
      <el-step v-for="s in steps" :key="s" :title="s" />
    </el-steps>

    <!-- 步骤一：输入创意 -->
    <div v-show="activeStep === 0" class="step-content">
      <!-- 输入模式选择 -->
      <el-radio-group v-model="inputMode" class="mode-group">
        <el-radio-button label="idea">一句话创意</el-radio-button>
        <el-radio-button label="upload">上传 txt</el-radio-button>
        <el-radio-button label="paste">粘贴大纲</el-radio-button>
      </el-radio-group>

      <!-- 一句话创意 -->
      <el-input
        v-if="inputMode === 'idea'"
        v-model="form.idea"
        type="textarea"
        :rows="4"
        placeholder="例如：一个穿越到赛博朋克世界的古代剑客，在霓虹都市中寻找失落的剑谱..."
        maxlength="500"
        show-word-limit
      />

      <!-- 上传 txt -->
      <el-upload
        v-else-if="inputMode === 'upload'"
        drag
        action="#"
        :auto-upload="false"
        :show-file-list="false"
        :before-upload="beforeUpload"
        accept=".txt"
      >
        <el-icon class="upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          将 txt 文件拖到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">仅支持 txt 格式文件</div>
        </template>
      </el-upload>
      <div v-if="form.fileName" class="uploaded-file">
        <el-icon><Document /></el-icon>
        <span>{{ form.fileName }}</span>
        <el-button text type="danger" @click="handleRemove">移除</el-button>
      </div>

      <!-- 粘贴大纲 -->
      <el-input
        v-else
        v-model="form.outline"
        type="textarea"
        :rows="6"
        placeholder="粘贴你的故事大纲，支持分场描述..."
        maxlength="5000"
        show-word-limit
      />
    </div>

    <!-- 步骤二：配置元信息 -->
    <div v-show="activeStep === 1" class="step-content">
      <el-form label-width="90px">
        <el-form-item label="项目标题" required>
          <el-input v-model="form.title" placeholder="请输入项目标题" maxlength="50" show-word-limit />
        </el-form-item>

        <el-form-item label="体裁">
          <div class="field-row">
            <el-select v-model="form.genre" style="flex: 1">
              <el-option v-for="g in genrePresets" :key="g" :label="g" :value="g" />
            </el-select>
            <el-input
              v-model="form.customGenre"
              placeholder="自定义体裁（可选）"
              style="flex: 1"
            />
          </div>
        </el-form-item>

        <el-form-item label="风格">
          <el-select v-model="form.style" style="width: 100%">
            <el-option v-for="s in stylePresets" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>

        <el-form-item label="目标集数">
          <el-input-number v-model="form.episodes" :min="1" :max="100" />
        </el-form-item>

        <el-form-item label="单集时长">
          <el-input-number v-model="form.duration" :min="1" :max="60" />
          <span class="unit">分钟</span>
        </el-form-item>

        <el-form-item label="输出比例">
          <el-radio-group v-model="form.ratio">
            <el-radio-button v-for="r in ratioOptions" :key="r" :label="r">{{ r }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
    </div>

    <!-- 步骤三：确认创建 -->
    <div v-show="activeStep === 2" class="step-content confirm-content">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="项目标题">{{ form.title }}</el-descriptions-item>
        <el-descriptions-item label="输入模式">
          {{ inputMode === 'idea' ? '一句话创意' : inputMode === 'upload' ? '上传 txt' : '粘贴大纲' }}
        </el-descriptions-item>
        <el-descriptions-item label="创意/大纲">
          <div class="outline-preview">
            {{ inputMode === 'idea' ? form.idea : form.outline }}
          </div>
        </el-descriptions-item>
        <el-descriptions-item label="体裁">{{ finalGenre }}</el-descriptions-item>
        <el-descriptions-item label="风格">{{ form.style }}</el-descriptions-item>
        <el-descriptions-item label="目标集数">{{ form.episodes }} 集</el-descriptions-item>
        <el-descriptions-item label="单集时长">{{ form.duration }} 分钟</el-descriptions-item>
        <el-descriptions-item label="输出比例">{{ form.ratio }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 底部按钮 -->
    <template #footer>
      <el-button @click="closeDialog">取消</el-button>
      <el-button v-if="activeStep > 0" @click="prevStep">上一步</el-button>
      <el-button type="primary" :loading="loading" @click="nextStep">
        {{ activeStep < 2 ? '下一步' : '创建项目' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-steps {
  margin-bottom: 28px;
}

.step-content {
  min-height: 200px;
}

.mode-group {
  margin-bottom: 20px;
}

.upload-icon {
  font-size: 48px;
  color: var(--ai-primary-color);
}

.uploaded-file {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 12px;
  background-color: var(--ai-bg-color);
  border-radius: 4px;
  font-size: 13px;
}

.uploaded-file span {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-row {
  display: flex;
  gap: 12px;
  width: 100%;
}

.unit {
  margin-left: 8px;
  font-size: 13px;
  color: var(--ai-text-secondary);
}

.confirm-content {
  max-height: 360px;
  overflow-y: auto;
}

.outline-preview {
  max-height: 100px;
  overflow-y: auto;
  white-space: pre-wrap;
  color: var(--ai-text-regular);
  font-size: 13px;
}
</style>
