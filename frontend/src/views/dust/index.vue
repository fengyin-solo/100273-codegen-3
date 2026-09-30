<template>
  <section class="page dust-page" data-module="dust">
    <header class="page-head">
      <div>
        <h2>扬尘监测管理</h2>
        <p class="page-desc">纸单读数先进入待核表，量程、空缺和重复抄录全部核清后，整批一次性导入台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showImport = !showImport">
          {{ showImport ? '收起导入区' : '整理读数待核' }}
        </button>
        <button class="btn" type="button" @click="loadAll">刷新数据</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ warning: item.danger }">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showImport" class="import-panel" @submit.prevent="submitImport">
      <div class="import-toolbar">
        <span>支持 CSV 或 JSON；同一点位同一时段以最后一次抄录为准。</span>
        <button class="btn ghost" type="button" @click="importText = sampleImport">填入示例</button>
      </div>
      <textarea v-model="importText" rows="8" placeholder="监测点位,时段,读数,抑尘措施,备注,抄录人"></textarea>
      <div class="form-foot">
        <span v-if="importMessage" :class="importOk ? 'success-text' : 'error-text'">{{ importMessage }}</span>
        <button class="btn primary" type="submit">生成待核表</button>
      </div>
    </form>

    <nav class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </nav>

    <section v-if="activeTab === 'points'">
      <h3>点位总览</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>点位编号</th><th>点位名称</th><th>量程</th><th>超标限值</th>
            <th>台账条数</th><th>超标条数</th><th>待核条数</th><th>措施未跟进</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="point in points" :key="point.id" :class="{ 'row-danger': point.超标条数 > 0 }">
            <td>{{ point.point_code }}</td>
            <td>{{ point.point_name }}</td>
            <td>{{ point.min_value }} ~ {{ point.max_value }} μg/m³</td>
            <td>{{ point.limit_value }} μg/m³</td>
            <td>{{ point.台账条数 }}</td>
            <td><strong :class="{ warning: point.超标条数 > 0 }">{{ point.超标条数 }}</strong></td>
            <td>{{ point.待核条数 }}</td>
            <td>{{ point.措施未跟进条数 }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="activeTab === 'reviews'">
      <form class="filter-bar" @submit.prevent="loadReviews">
        <label class="filter-item">
          <span>批次</span>
          <select v-model="reviewFilters.batch_id">
            <option value="">全部批次</option>
            <option v-for="batch in batches" :key="batch.batch_id" :value="batch.batch_id">
              {{ batch.batch_id }}（{{ batch.状态 }}）
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>状态</span>
          <select v-model="reviewFilters.status">
            <option value="">全部状态</option>
            <option v-for="status in reviewStatuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>关键字</span>
          <input v-model="reviewFilters.keyword" placeholder="点位 / 时段 / 备注" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>

      <table class="data-table batch-table">
        <thead>
          <tr>
            <th>批次号</th><th>导入时间</th><th>状态</th><th>总行数</th><th>有效行</th>
            <th>待核</th><th>退回</th><th>已核</th><th>超标</th><th>措施未跟进</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="batch.batch_id">
            <td>{{ batch.batch_id }}</td>
            <td>{{ batch.导入时间 }}</td>
            <td><span class="status" :class="batchStatusClass(batch.状态)">{{ batch.状态 }}</span></td>
            <td>{{ batch.总行数 }}</td><td>{{ batch.有效行数 }}</td><td>{{ batch.待核条数 }}</td>
            <td :class="{ warning: batch.退回条数 > 0 }">{{ batch.退回条数 }}</td>
            <td>{{ batch.已核条数 }}</td><td>{{ batch.超标条数 }}</td>
            <td :class="{ warning: batch.措施未跟进条数 > 0 }">{{ batch.措施未跟进条数 }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="selectBatch(batch.batch_id)">查看</button>
              <button class="link" type="button" @click="verifyBatch(batch.batch_id)">整批核验</button>
              <button
                class="link"
                type="button"
                :disabled="!batch.可入账"
                :title="batch.可入账 ? '' : '待核表没过，不能导入台账'"
                @click="commitBatch(batch.batch_id)"
              >
                整批入账
              </button>
            </td>
          </tr>
          <tr v-if="!batches.length"><td colspan="11" class="empty-state">暂无待核批次</td></tr>
        </tbody>
      </table>

      <h3>待核表明细</h3>
      <table class="data-table review-table">
        <thead>
          <tr>
            <th>ID</th><th>批次/行号</th><th>点位</th><th>时段</th><th>读数</th>
            <th>量程</th><th>抑尘措施</th><th>管控备注</th><th>状态</th><th>原因/覆盖</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in reviews" :key="row.id" :class="rowClass(row)">
            <td>{{ row.id }}</td>
            <td>{{ row.batch_id }} / 第{{ row.source_row }}行</td>
            <td>{{ row.监测点位 }}<br><small>{{ row.点位名称 }}</small></td>
            <td>{{ row.时段 }}</td>
            <td>
              <strong :class="{ warning: row.超标 }">{{ formatValue(row.读数) }}</strong>
              <small v-if="row.超标">超标</small>
            </td>
            <td>{{ row.量程下限 }}~{{ row.量程上限 }}</td>
            <td :class="{ warning: row.措施未跟进 }">{{ row.抑尘措施 }}</td>
            <td>{{ row.备注 || '—' }}</td>
            <td><span class="status" :class="rowStatusClass(row.状态)">{{ row.状态 }}</span></td>
            <td>{{ row.退回原因 || row.覆盖说明 || '—' }}</td>
            <td class="row-actions review-actions">
              <template v-if="canPass(row)"><button class="link" type="button" @click="rowAction('通过', row)">通过</button></template>
              <button
                v-if="canReject(row)"
                class="link danger"
                type="button"
                @click="rowAction('退回', row)"
              >退回</button>
              <button v-if="canCorrect(row)" class="link" type="button" @click="correctRow(row)">修正</button>
            </td>
          </tr>
          <tr v-if="!reviews.length"><td colspan="11" class="empty-state">暂无符合条件的待核记录</td></tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>{{ actionMessage }}</span></footer>
    </section>

    <section v-if="activeTab === 'ledger'">
      <form class="filter-bar" @submit.prevent="loadLedger">
        <label class="filter-item"><span>月份</span><input v-model="ledgerFilters.month" placeholder="YYYY-MM" /></label>
        <label class="filter-item"><span>点位</span><input v-model="ledgerFilters.point" placeholder="点位编号" /></label>
        <label class="check-item">
          <input v-model="ledgerFilters.only_over_limit" type="checkbox" @change="loadLedger" /> 只看超标
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetLedgerFilters">重置</button>
      </form>
      <table class="data-table ledger-table">
        <thead>
          <tr>
            <th>点位</th><th>时段</th><th>读数</th><th>抑尘措施</th><th>备注</th>
            <th>抄录人</th><th>超标</th><th>覆盖来源</th><th>批次</th><th>入账时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger" :key="row.id" :class="{ 'row-danger': row.超标 }">
            <td>{{ row.监测点位 }}<br><small>{{ row.点位名称 }}</small></td>
            <td>{{ row.时段 }}</td>
            <td><strong :class="{ warning: row.超标 }">{{ formatValue(row.读数) }}</strong></td>
            <td :class="{ warning: row.措施未跟进 }">{{ row.抑尘措施 }}</td>
            <td>{{ row.备注 || '—' }}</td>
            <td>{{ row.抄录人 }}</td>
            <td>{{ row.超标 ? '是' : '否' }}</td>
            <td>{{ row.覆盖来源 || '—' }}</td>
            <td>{{ row.batch_id }}</td>
            <td>{{ row.入账时间 }}</td>
          </tr>
          <tr v-if="!ledger.length"><td colspan="10" class="empty-state">暂无台账数据</td></tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>本页 {{ ledger.length }} 行，台账总计 {{ ledgerTotal }} 行</span>
        <span v-if="ledgerFilters.month">当前月份：{{ ledgerFilters.month }}</span>
      </footer>
    </section>

    <section v-if="activeTab === 'report'">
      <form class="filter-bar" @submit.prevent="loadReport">
        <label class="filter-item"><span>月报月份</span><input v-model="reportMonth" placeholder="YYYY-MM" /></label>
        <button class="btn primary" type="submit">生成月报</button>
      </form>
      <div v-if="report" class="stat-row">
        <article class="stat-card"><span class="stat-label">月报行数</span><strong>{{ report.report_rows }}</strong></article>
        <article class="stat-card"><span class="stat-label">超标条数</span><strong class="warning">{{ report.超标条数 }}</strong></article>
        <article class="stat-card"><span class="stat-label">措施未跟进</span><strong class="warning">{{ report.措施未跟进条数 }}</strong></article>
        <article class="stat-card"><span class="stat-label">平均读数</span><strong>{{ report.平均读数 ?? '—' }}</strong></article>
      </div>
      <p v-if="report" class="page-desc">月报行数按台账接口同一筛选口径实时计算，与页面显示的台账总计一致。</p>
      <table v-if="report" class="data-table">
        <thead>
          <tr><th>点位</th><th>时段</th><th>读数</th><th>抑尘措施</th><th>备注</th><th>超标</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in report.items" :key="row.id" :class="{ 'row-danger': row.超标 }">
            <td>{{ row.监测点位 }}</td><td>{{ row.时段 }}</td>
            <td>{{ formatValue(row.读数) }}</td><td>{{ row.抑尘措施 }}</td>
            <td>{{ row.备注 || '—' }}</td><td>{{ row.超标 ? '是' : '否' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type ActionResponse = { ok: boolean; message: string; entry?: Record<string, unknown> }
type DataRow = Record<string, any>

const ENDPOINT = '/api/dust'
const tabs = [
  { key: 'points', label: '点位总览' },
  { key: 'reviews', label: '待核表' },
  { key: 'ledger', label: '扬尘台账' },
  { key: 'report', label: '月报' },
] as const
const reviewStatuses = ['待核', '已核', '退回', '已覆盖', '同批重复', '重复导入', '已入账']

const activeTab = ref<(typeof tabs)[number]['key']>('points')
const showImport = ref(false)
const points = ref<DataRow[]>([])
const batches = ref<DataRow[]>([])
const reviews = ref<DataRow[]>([])
const ledger = ref<DataRow[]>([])
const ledgerTotal = ref(0)
const report = ref<DataRow | null>(null)
const actionMessage = ref('')
const importText = ref('')
const importMessage = ref('')
const importOk = ref(false)
const reportMonth = ref('2026-09')
const reviewFilters = reactive({ batch_id: '', status: '', keyword: '', page: 1, size: 200 })
const ledgerFilters = reactive<{ month: string; point: string; only_over_limit: boolean; page: number; size: number }>({
  month: '2026-09',
  point: '',
  only_over_limit: false,
  page: 1,
  size: 200,
})

const sampleImport = `监测点位,时段,读数,抑尘措施,备注,抄录人
DUST-01,2026-09-10 08:00,120,已喷淋,首次抄录,张工
DUST-01,2026-09-10 08:00,135,已喷淋,补抄覆盖前条,张工
DUST-02,2026-09-10 08:00,,未喷淋,读数空缺,李工
DUST-03,2026-09-10 08:00,190,未喷淋,超标且措施未跟上,王工
DUST-04,2026-09-10 08:00,1200,已喷淋,超出量程,赵工`

const stats = computed(() => [
  { label: '监测点位数', value: points.value.length, danger: false },
  { label: '点位超标条数', value: points.value.reduce((sum, row) => sum + Number(row.超标条数 || 0), 0), danger: true },
  { label: '待处理记录', value: points.value.reduce((sum, row) => sum + Number(row.待核条数 || 0), 0), danger: false },
  { label: '措施未跟进', value: points.value.reduce((sum, row) => sum + Number(row.措施未跟进条数 || 0), 0), danger: true },
])

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as T
}

async function postAction(path: string, body: unknown = {}): Promise<ActionResponse> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return (await response.json()) as ActionResponse
}

async function loadPoints() {
  const payload = await getJson<{ items: DataRow[] }>(`${ENDPOINT}/points`)
  points.value = payload.items ?? []
}

async function loadBatches() {
  const payload = await getJson<{ items: DataRow[] }>(`${ENDPOINT}/batches`)
  batches.value = payload.items ?? []
}

async function loadReviews() {
  const params = new URLSearchParams()
  Object.entries(reviewFilters).forEach(([key, value]) => {
    if (value !== '' && value !== null) params.set(key, String(value))
  })
  const payload = await getJson<{ items: DataRow[]; total: number }>(`${ENDPOINT}/reviews?${params}`)
  reviews.value = payload.items ?? []
}

async function loadLedger() {
  const params = new URLSearchParams()
  Object.entries(ledgerFilters).forEach(([key, value]) => {
    if (value !== '' && value !== null) params.set(key, String(value))
  })
  const payload = await getJson<{ items: DataRow[]; total: number }>(`${ENDPOINT}/ledger?${params}`)
  ledger.value = payload.items ?? []
  ledgerTotal.value = payload.total ?? 0
}

async function loadReport() {
  report.value = await getJson<DataRow>(`${ENDPOINT}/monthly-report?month=${encodeURIComponent(reportMonth.value)}`)
}

async function loadAll() {
  actionMessage.value = ''
  try {
    await Promise.all([loadPoints(), loadBatches(), loadReviews(), loadLedger()])
    if (reportMonth.value) await loadReport()
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '扬尘数据加载失败'
  }
}

function parseImportText(text: string): unknown[] | string {
  const trimmed = text.trim()
  if (!trimmed) return []
  if (trimmed.startsWith('[')) return JSON.parse(trimmed)
  const lines = trimmed.split(/\r?\n/).filter(Boolean)
  const headers = splitCsvLine(lines[0])
  return lines.slice(1).map((line) => {
    const values = splitCsvLine(line)
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? '']))
  })
}

function splitCsvLine(line: string): string[] {
  const result: string[] = []
  let current = ''
  let quoted = false
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    if (char === '"' && line[index + 1] === '"') {
      current += '"'
      index += 1
    } else if (char === '"') {
      quoted = !quoted
    } else if ((char === ',' || char === '\t') && !quoted) {
      result.push(current.trim())
      current = ''
    } else {
      current += char
    }
  }
  result.push(current.trim())
  return result
}

async function submitImport() {
  importMessage.value = ''
  try {
    const values = parseImportText(importText.value)
    const result = await postAction(`${ENDPOINT}/imports`, { values })
    importOk.value = result.ok
    importMessage.value = result.message
    if (result.ok && result.entry?.batch_id) {
      reviewFilters.batch_id = String(result.entry.batch_id)
      reviewFilters.status = ''
      await loadAll()
    }
  } catch (error) {
    importOk.value = false
    importMessage.value = error instanceof Error ? error.message : '待核表生成失败'
  }
}

function selectBatch(batchId: string) {
  reviewFilters.batch_id = batchId
  void loadReviews()
}

async function runPost(path: string, body: unknown = {}) {
  actionMessage.value = ''
  const result = await postAction(path, body)
  actionMessage.value = result.message
  if (!result.ok) return
  await loadAll()
}

function verifyBatch(batchId: string) {
  void runPost(`${ENDPOINT}/batches/${batchId}/verify`)
}

function commitBatch(batchId: string) {
  if (!window.confirm('待核表通过后将一次性入账，确认继续？')) return
  void runPost(`${ENDPOINT}/batches/${batchId}/commit`)
}

async function rowAction(action: string, row: DataRow) {
  const values: DataRow = { action }
  if (action === '退回') {
    const reason = window.prompt('请输入退回原因', row.退回原因 || '人工核验退回')
    if (reason === null) return
    values.reason = reason
  }
  await runPost(`${ENDPOINT}/reviews/${row.id}/actions`, values)
}

async function correctRow(row: DataRow) {
  const reading = window.prompt('修正读数（留空表示读数空缺）', row.读数 ?? '')
  if (reading === null) return
  const measure = window.prompt('抑尘措施（已喷淋/未喷淋）', row.抑尘措施 || '')
  if (measure === null) return
  const remark = window.prompt('管控备注', row.备注 || '')
  if (remark === null) return
  await runPost(`${ENDPOINT}/reviews/${row.id}/actions`, {
    action: '修正',
    读数: reading,
    抑尘措施: measure,
    备注: remark,
  })
}

function resetLedgerFilters() {
  ledgerFilters.month = ''
  ledgerFilters.point = ''
  ledgerFilters.only_over_limit = false
  void loadLedger()
}

function formatValue(value: unknown) {
  return value === null || value === undefined || value === '' ? '空缺' : value
}
function canPass(row: DataRow) { return row.状态 === '待核' }
function canReject(row: DataRow) { return ['待核', '已核'].includes(row.状态) }
function canCorrect(row: DataRow) { return ['退回', '待核'].includes(row.状态) }
function rowClass(row: DataRow) {
  return {
    'row-danger': row.状态 === '退回' || row.超标,
    'row-muted': ['已覆盖', '同批重复', '重复导入'].includes(row.状态),
  }
}
function rowStatusClass(status: string) {
  return {
    'status-pending': status === '待核',
    'status-pass': status === '已核' || status === '已入账',
    'status-danger': status === '退回',
    'status-muted': status === '已覆盖' || status === '同批重复' || status === '重复导入',
  }
}
function batchStatusClass(status: string) {
  return {
    'status-pending': status === '待核' || status === '待入账',
    'status-pass': status === '已入账',
    'status-danger': status === '有退回',
  }
}

onMounted(loadAll)
</script>
