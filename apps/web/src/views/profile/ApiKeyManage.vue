<!--
  P15 API Key 管理页
  管理各厂商 API Key：列表展示（厂商/能力/掩码显示）、添加/编辑弹窗、
  「测试连通性」按钮调用 verifyKey、删除二次确认
  密钥经后端 AES-256 加密保存，前端仅做掩码展示
-->
<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import request from '@/api/request'

/** API Key 项数据结构 */
interface ApiKeyItem {
  /** Key ID */
  id: string
  /** 厂商 */
  provider: string
  /** 能力类型 */
  capability: '文本' | '图像' | '视频' | '语音'
  /** 掩码后的 Key */
  masked_key: string
  /** 是否已验证连通 */
  verified: boolean
  /** 创建时间 */
  created_at: string
}

/** 加载态 */
const loading = ref(false)
/** Key 列表 */
const keyList = ref<ApiKeyItem[]>([])
/** 新增/编辑弹窗显隐 */
const dialogVisible = ref(false)
/** 是否为编辑模式 */
const isEdit = ref(false)
/** 当前编辑的 Key ID */
const editingId = ref('')
/** 正在测试连通性的 Key ID */
const verifyingId = ref('')

/** 表单数据 */
const keyForm = reactive({
  provider: '',
  capability: '文本' as ApiKeyItem['capability'],
  api_key: '',
})

/** 表单校验规则 */
const keyRules: FormRules = {
  provider: [{ required: true, message: '请选择厂商', trigger: 'change' }],
  capability: [{ required: true, message: '请选择能力', trigger: 'change' }],
  api_key: [
    { required: true, message: '请输入 API Key', trigger: 'blur' },
    { min: 8, message: 'Key 长度至少 8 位', trigger: 'blur' },
  ],
}

/** 厂商选项 */
const providerOptions = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
  { label: '通义千问', value: 'qwen' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: '月之暗面 Moonshot', value: 'moonshot' },
  { label: 'Stability AI', value: 'stability' },
  { label: 'Midjourney', value: 'midjourney' },
  { label: 'Runway', value: 'runway' },
  { label: '可灵 Kling', value: 'kling' },
  { label: 'Sambert', value: 'sambert' },
  { label: 'Fish Audio', value: 'fishaudio' },
]

const keyFormRef = ref<FormInstance>()

/**
 * 获取厂商中文名
 * @param value - 厂商 value
 * @returns 中文标签
 */
function getProviderLabel(value: string): string {
  return providerOptions.find((p) => p.value === value)?.label || value
}

/**
 * 拉取 API Key 列表
 */
async function fetchKeys(): Promise<void> {
  loading.value = true
  try {
    const res = await request.get('/users/me/api-keys')
    keyList.value = res as unknown as ApiKeyItem[]
  } catch (e) {
    console.error('拉取 API Key 列表失败', e)
    keyList.value = []
  } finally {
    loading.value = false
  }
}

/**
 * 打开新增弹窗
 */
function openAddDialog(): void {
  isEdit.value = false
  editingId.value = ''
  keyForm.provider = ''
  keyForm.capability = '文本'
  keyForm.api_key = ''
  dialogVisible.value = true
}

/**
 * 打开编辑弹窗
 * @param item - 待编辑的 Key 项
 */
function openEditDialog(item: ApiKeyItem): void {
  isEdit.value = true
  editingId.value = item.id
  keyForm.provider = item.provider
  keyForm.capability = item.capability
  keyForm.api_key = '' // 编辑时不回填明文
  dialogVisible.value = true
}

/**
 * 保存 Key（新增或编辑）
 */
async function saveKey(): Promise<void> {
  try {
    await keyFormRef.value?.validate()
  } catch (e) {
    return
  }
  try {
    if (isEdit.value) {
      await request.put(`/users/me/api-keys/${editingId.value}`, {
        provider: keyForm.provider,
        capability: keyForm.capability,
        api_key: keyForm.api_key,
      })
      ElMessage.success('Key 已更新')
    } else {
      await request.post('/users/me/api-keys', {
        provider: keyForm.provider,
        capability: keyForm.capability,
        api_key: keyForm.api_key,
      })
      ElMessage.success('Key 已添加')
    }
    dialogVisible.value = false
    fetchKeys()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

/**
 * 测试 Key 连通性
 * 后端解密存储的真实 Key 发起测试，返回 { valid, latency_ms, models }
 * @param item - 待测试的 Key 项
 */
async function handleVerify(item: ApiKeyItem): Promise<void> {
  verifyingId.value = item.id
  try {
    const res = await request.post(`/users/me/api-keys/${item.id}/verify`) as {
      valid: boolean
      latency_ms: number
      models: string[]
    }
    if (res.valid) {
      item.verified = true
      ElMessage.success(`连通性测试通过（${res.latency_ms}ms）`)
    } else {
      item.verified = false
      ElMessage.error('连通性测试失败，请检查 Key 是否正确')
    }
  } catch (e) {
    item.verified = false
    ElMessage.error('连通性测试失败')
  } finally {
    verifyingId.value = ''
  }
}

/**
 * 删除 Key（二次确认）
 * @param item - 待删除的 Key 项
 */
async function handleDelete(item: ApiKeyItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除「${getProviderLabel(item.provider)}」的 API Key 吗？删除后不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' },
    )
    await request.delete(`/users/me/api-keys/${item.id}`)
    ElMessage.success('Key 已删除')
    fetchKeys()
  } catch (e) {
    // 用户取消，不提示
  }
}

onMounted(() => {
  fetchKeys()
})
</script>

<template>
  <div class="api-key-manage" v-loading="loading">
    <div class="page-header">
      <h2 class="page-title">API Key 管理</h2>
      <el-button type="primary" @click="openAddDialog">
        <el-icon><Plus /></el-icon>
        添加 Key
      </el-button>
    </div>

    <el-alert
      title="API Key 经后端 AES-256 加密存储，前端仅展示掩码，请勿将 Key 泄露给他人"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-card shadow="never">
      <el-table :data="keyList" stripe>
        <el-table-column prop="provider" label="厂商" min-width="140">
          <template #default="{ row }: { row: any }">{{ getProviderLabel(row.provider) }}</template>
        </el-table-column>
        <el-table-column prop="capability" label="能力" width="100">
          <template #default="{ row }: { row: any }">
            <el-tag size="small" effect="plain">{{ row.capability }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="masked_key" label="Key" min-width="220">
          <template #default="{ row }: { row: any }">
            <span class="masked-key">{{ row.masked_key }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }: { row: any }">
            <el-tag v-if="row.verified" type="success" size="small">已验证</el-tag>
            <el-tag v-else-if="row.builtin" type="warning" size="small">系统内置</el-tag>
            <el-tag v-else type="info" size="small">未验证</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }: { row: any }">
            {{ row.builtin ? '—' : row.created_at }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }: { row: any }">
            <el-button
              type="primary"
              text
              size="small"
              :loading="verifyingId === row.id"
              @click="handleVerify(row)"
            >
              测试连通性
            </el-button>
            <template v-if="!row.builtin">
              <el-button text size="small" @click="openEditDialog(row)">编辑</el-button>
              <el-button type="danger" text size="small" @click="handleDelete(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="keyList.length === 0" description="暂无 API Key，点击右上角添加" />
    </el-card>

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑 API Key' : '添加 API Key'"
      width="500px"
      destroy-on-close
    >
      <el-form
        ref="keyFormRef"
        :model="keyForm"
        :rules="keyRules"
        label-width="80px"
      >
        <el-form-item label="厂商" prop="provider">
          <el-select v-model="keyForm.provider" placeholder="请选择厂商" style="width: 100%">
            <el-option
              v-for="opt in providerOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="能力" prop="capability">
          <el-select v-model="keyForm.capability" placeholder="请选择能力" style="width: 100%">
            <el-option label="文本" value="文本" />
            <el-option label="图像" value="图像" />
            <el-option label="视频" value="视频" />
            <el-option label="语音" value="语音" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="keyForm.api_key"
            type="password"
            show-password
            :placeholder="isEdit ? '留空则不修改' : '请输入 API Key'"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveKey">{{ isEdit ? '保存' : '添加' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.api-key-manage {
  max-width: 1100px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  color: var(--ai-text-primary);
}

.masked-key {
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: var(--ai-text-regular);
  letter-spacing: 1px;
}
</style>
