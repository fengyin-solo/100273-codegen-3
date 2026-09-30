<template>
  <section class="page" data-module="dust">
    <header class="page-head">
      <div>
        <h2>扬尘监测 · 先核后入</h2>
        <p class="page-desc">
          抄表读数先整理成待核表，逐条与点位量程比对；超量程/读数空缺退回，
          同点位同时段以最后一次抄录为准并注明覆盖，同一份读数重复导入只留一条。
          待核表没过不许入账，入账一次落完不留半批。
        </p>
      </div>
    </header>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-item"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
        <span v-if="tab.key === 'review' && pendingBadge" class="tab-badge">{{ pendingBadge }}</span>
      </button>
    </nav>

    <p v-if="message" class="form-msg" :class="{ 'error-text': !messageOk }">{{ message }}</p>

    <!-- ============================== 点位总览 ============================== -->
    <div v-if="activeTab === 'points'">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">监测点位</span>
          <strong class="stat-value">{{ points.length }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">已入账读数</span>
          <strong class="stat-value">{{ ledgerTotal }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">超标条数（实时）</span>
          <strong class="stat-value exceed">{{ exceedTotal }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">待处理读数</span>
          <strong class="stat-value">{{ pendingReadingCount }}</strong>
        </article>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>点位编号</th><th>点位名称</th><th>PM10量程</th><th>PM10预警值</th>
            <th>PM2.5量程</th><th>PM2.5预警值</th><th>已入账条数</th><th>超标条数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="point in points" :key="point['点位编号']">
            <td>{{ point['点位编号'] }}</td>
            <td>{{ point['点位名称'] }}</td>
            <td>{{ point['PM10量程下限'] }} ~ {{ point['PM10量程上限'] }}</td>
            <td>＞{{ point['PM10预警值'] }}</td>
            <td>{{ point['PM2.5量程下限'] }} ~ {{ point['PM2.5量程上限'] }}</td>
            <td>＞{{ point['PM2.5预警值'] }}</td>
            <td>{{ point['入账条数'] }}</td>
            <td>
              <span class="badge" :class="point['超标条数'] ? 'badge-reject' : 'badge-pass'">
                {{ point['超标条数'] }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>超标条数在批次入账后自动更新，与月报同口径汇总台账。</span>
      </footer>
    </div>

    <!-- ============================== 待核导入 ============================== -->
    <div v-if="activeTab === 'review'">
      <div class="review-layout">
        <div class="review-col">
          <h3 class="block-title">1. 录入/粘贴抄表读数</h3>
          <p class="block-hint">
            每行一条，顺序即抄录顺序（后抄的行覆盖先抄的行）。
            列顺序：点位编号, 抄录时段, PM10, PM2.5, 抑尘措施, 抄录人；逗号或制表符分隔，首行可留表头。
          </p>
          <textarea
            v-model="pasteText"
            class="paste-box"
            rows="8"
            placeholder="D-01,2026-10-02 08:00,96,45,喷淋正常,王强&#10;D-02,2026-10-02 08:00,168,80,未喷淋,李军"
          ></textarea>
          <div class="btn-row">
            <button class="btn primary" type="button" @click="parsePaste">解析到下方表格</button>
            <button class="btn ghost" type="button" @click="loadExample">填入示例</button>
          </div>

          <h3 class="block-title">2. 待导入读数（可直接修改）</h3>
          <table class="data-table edit-table">
            <thead>
              <tr>
                <th>点位编号</th><th>抄录时段</th><th>PM10</th><th>PM2.5</th>
                <th>抑尘措施</th><th>抄录人</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in draftRows" :key="index">
                <td><input v-model="row.point_code" placeholder="D-01" /></td>
                <td><input v-model="row.period" placeholder="2026-10-02 08:00" /></td>
                <td><input v-model="row.pm10" class="num-input" placeholder="读数" /></td>
                <td><input v-model="row.pm25" class="num-input" placeholder="读数" /></td>
                <td><input v-model="row.measure" placeholder="喷淋/雾炮/未落实" /></td>
                <td><input v-model="row.recorder" placeholder="抄录人" /></td>
                <td><button class="link danger" type="button" @click="draftRows.splice(index, 1)">删除</button></td>
            </tr>
            </tbody>
          </table>
          <div class="btn-row">
            <button class="btn" type="button" @click="addDraftRow">加一行</button>
            <button class="btn primary" type="button" :disabled="importing" @click="submitImport">
              {{ importing ? '导入中…' : '整理为待核表' }}
            </button>
          </div>
        </div>

        <div class="review-col">
          <h3 class="block-title">3. 导入批次</h3>
          <table class="data-table">
            <thead>
              <tr><th>批次号</th><th>状态</th><th>原始</th><th>通过</th><th>退回</th><th>重复</th><th></th></tr>
            </thead>
            <tbody>
              <tr
                v-for="batch in batches"
                :key="batch.id"
                :class="{ 'batch-active': selectedBatchId === batch.id }"
              >
                <td>{{ batch['批次号'] }}</td>
                <td><span class="badge" :class="batchBadgeClass(batch['状态'])">{{ batch['状态'] }}</span></td>
                <td>{{ batch['原始行数'] }}</td>
                <td>{{ batch['通过数'] }}</td>
                <td :class="{ 'error-text': batch['退回数'] > 0 }">{{ batch['退回数'] }}</td>
                <td>{{ batch['重复忽略数'] }}</td>
                <td><button class="link" type="button" @click="openBatch(batch.id)">看待核表</button></td>
              </tr>
              <tr v-if="!batches.length"><td colspan="7" class="empty-state">暂无批次</td></tr>
            </tbody>
          </table>

          <template v-if="currentBatch">
            <h3 class="block-title">
              4. 待核表 · {{ currentBatch['批次号'] }}
            </h3>
            <div class="batch-meta">
              <span>状态：<span class="badge" :class="batchBadgeClass(currentBatch['状态'])">{{ currentBatch['状态'] }}</span></span>
              <span>导入：{{ currentBatch['导入时间'] }}</span>
              <span v-if="currentBatch['入账时间']">入账：{{ currentBatch['入账时间'] }}</span>
              <span v-if="!currentBatch.can_post && currentBatch['状态'] === '待核'" class="error-text">
                待核表未过，不许导入台账
              </span>
              <span v-else-if="currentBatch.can_post" class="pass-text">待核表已过，可以入账</span>
            </div>
            <table class="data-table reading-table">
              <thead>
                <tr>
                  <th>原行</th><th>点位</th><th>抄录时段</th><th>PM10</th><th>PM2.5</th>
                  <th>抑尘措施/备注</th><th>核验结论</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in currentBatch.rows" :key="row.id" :class="rowRowClass(row)">
                  <td>{{ row['行号'] }}</td>
                  <td>{{ row['点位编号'] }}</td>
                  <td>{{ row['抄录时段'] }}</td>
                  <td :class="{ 'exceed-cell': row['超标项']?.includes('PM10') }">{{ row['PM10读数'] || '空缺' }}</td>
                  <td :class="{ 'exceed-cell': row['超标项']?.includes('PM2.5') }">{{ row['PM2.5读数'] || '空缺' }}</td>
                  <td class="note-cell">
                    <div>{{ row['抑尘措施'] }}</div>
                    <div v-if="row['措施备注']" class="measure-note">⚠ {{ row['措施备注'] }}</div>
                  </td>
                  <td class="note-cell">
                    <div><span class="badge" :class="rowBadgeClass(row['审核状态'])">{{ row['审核状态'] }}</span></div>
                    <div v-if="row['退回原因']" class="error-text">↩ {{ row['退回原因'] }}</div>
                    <div v-if="row['覆盖说明']" class="cover-note">⇄ {{ row['覆盖说明'] }}</div>
                    <div v-if="row['重复说明']" class="dup-note">⧉ {{ row['重复说明'] }}</div>
                    <div v-if="row['超标项']" class="exceed-note">超标项：{{ row['超标项'] }}（超预警值，入账后计入超标条数）</div>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="currentBatch['状态'] === '待核'" class="btn-row">
              <button class="btn" type="button" @click="verifyBatch">重新逐条核验</button>
              <button
                class="btn primary"
                type="button"
                :disabled="!currentBatch.can_post || posting"
                :title="currentBatch.can_post ? '' : '存在退回行，待核表通过后才能入账'"
                @click="postBatch"
              >
                {{ posting ? '入账中…' : '整批一次性入账' }}
              </button>
              <button class="btn ghost danger-btn" type="button" @click="discardBatch">整份退回（废弃）</button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ================================ 台账 ================================ -->
    <div v-if="activeTab === 'ledger'">
      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>点位编号</span>
          <input v-model="ledgerFilter.point_code" placeholder="按点位检索" />
        </label>
        <label class="filter-item">
          <span>月份</span>
          <input v-model="ledgerFilter.month" placeholder="2026-09" />
        </label>
        <label class="filter-item check-item">
          <input v-model="ledgerFilter.only_exceed" type="checkbox" />
          <span>只看超标</span>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetLedgerFilter">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>点位编号</th><th>点位名称</th><th>抄录时段</th><th>PM10</th><th>PM2.5</th>
            <th>是否超标</th><th>抑尘措施</th><th>措施备注</th><th>抄录人</th><th>入账批次</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="Number(row.id)" :class="{ 'row-exceed': row['是否超标'] }">
            <td>{{ row['点位编号'] }}</td>
            <td>{{ row['点位名称'] }}</td>
            <td>{{ row['抄录时段'] }}</td>
            <td>{{ row['PM10读数'] }}</td>
            <td>{{ row['PM2.5读数'] }}</td>
            <td>
              <span class="badge" :class="row['是否超标'] ? 'badge-reject' : 'badge-pass'">
                {{ row['是否超标'] ? `超标（${row['超标项']}）` : '达标' }}
              </span>
            </td>
            <td>{{ row['抑尘措施'] }}</td>
            <td>{{ row['措施备注'] || '—' }}</td>
            <td>{{ row['抄录人'] }}</td>
            <td>{{ row['入账批次'] }}</td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td colspan="10" class="empty-state">当前条件下没有入账记录</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ ledgerTotal }} 条台账记录（与同条件月报明细行数一致）</span>
        <span v-if="ledgerFilter.month">当前月份：{{ ledgerFilter.month }}</span>
      </footer>
    </div>

    <!-- ================================ 月报 ================================ -->
    <div v-if="activeTab === 'report'">
      <form class="filter-bar" @submit.prevent="reloadReport">
        <label class="filter-item">
          <span>报表月份</span>
          <input v-model="reportMonth" placeholder="2026-09" />
        </label>
        <button class="btn" type="submit">生成月报</button>
      </form>
      <div v-if="report" class="stat-row">
        <article class="stat-card">
          <span class="stat-label">月报行数（=台账页面行数）</span>
          <strong class="stat-value">{{ report.total }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">月内超标条数</span>
          <strong class="stat-value exceed">{{ report.exceed_total }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">覆盖点位</span>
          <strong class="stat-value">{{ report.summary.length }}</strong>
        </article>
      </div>
      <h3 class="block-title">点位汇总</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>点位编号</th><th>点位名称</th><th>入账条数</th><th>超标条数</th>
            <th>PM10平均</th><th>PM10最高</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in report?.summary" :key="String(item['点位编号'])">
            <td>{{ item['点位编号'] }}</td>
            <td>{{ item['点位名称'] }}</td>
            <td>{{ item['入账条数'] }}</td>
            <td :class="{ 'error-text': Number(item['超标条数']) > 0 }">{{ item['超标条数'] }}</td>
            <td>{{ item['PM10平均'] ?? '—' }}</td>
            <td>{{ item['PM10最高'] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
      <h3 class="block-title">明细（{{ report?.total }} 行，与台账页面同一份数据）</h3>
      <table class="data-table">
        <thead>
          <tr><th>点位编号</th><th>抄录时段</th><th>PM10</th><th>PM2.5</th><th>超标</th><th>抑尘措施备注</th><th>入账批次</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in report?.items" :key="Number(row.id)" :class="{ 'row-exceed': row['是否超标'] }">
            <td>{{ row['点位编号'] }}</td>
            <td>{{ row['抄录时段'] }}</td>
            <td>{{ row['PM10读数'] }}</td>
            <td>{{ row['PM2.5读数'] }}</td>
            <td>{{ row['超标项'] || '—' }}</td>
            <td>{{ row['措施备注'] || '—' }}</td>
            <td>{{ row['入账批次'] }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type ReadingRow = {
  point_code: string
  period: string
  pm10: string
  pm25: string
  measure: string
  measure_note?: string
  recorder: string
}

type Batch = {
  id: number
  批次号: string
  状态: string
  导入时间: string
  入账时间: string | null
  原始行数: number
  通过数: number
  退回数: number
  重复忽略数: number
  can_post?: boolean
  rows?: StagingRow[]
}

type StagingRow = Record<string, string | number | boolean | null> & {
  id: number
  行号: number
  点位编号: string
  抄录时段: string
  PM10读数: string
  'PM2.5读数': string
  抑尘措施: string
  措施备注: string
  审核状态: string
  退回原因: string
  覆盖说明: string
  重复说明: string
  超标项: string
}

const tabs = [
  { key: 'points', label: '点位总览' },
  { key: 'review', label: '待核导入' },
  { key: 'ledger', label: '扬尘台账' },
  { key: 'report', label: '月报' },
] as const

const activeTab = ref<(typeof tabs)[number]['key']>('points')
const message = ref('')
const messageOk = ref(true)

const points = ref<Record<string, string | number>[]>([])
const exceedTotal = ref(0)
const ledgerTotal = ref(0)
const pendingReadingCount = ref(0)

const batches = ref<Batch[]>([])
const selectedBatchId = ref<number | null>(null)
const currentBatch = ref<Batch | null>(null)

const pasteText = ref('')
const draftRows = ref<ReadingRow[]>([])
const importing = ref(false)
const posting = ref(false)

const ledgerRows = ref<Record<string, string | number | boolean | null>[]>([])
const ledgerFilter = ref({ point_code: '', month: '', only_exceed: false })

const reportMonth = ref('2026-09')
const report = ref<Awaited<ReturnType<typeof fetchReport>> | null>(null)

const pendingBadge = computed(() =>
  batches.value
    .filter((batch) => batch.状态 === '待核')
    .reduce((sum, batch) => sum + batch.通过数 + batch.退回数, 0)
)

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function switchTab(key: (typeof tabs)[number]['key']) {
  activeTab.value = key
  message.value = ''
  if (key === 'points') void loadPoints()
  if (key === 'review') void loadBatches()
  if (key === 'ledger') void reloadLedger()
  if (key === 'report') void reloadReport()
}

async function loadPoints() {
  const response = await request('/api/dust/points')
  if (!response.ok) {
    flash('点位总览读取失败', false)
    return
  }
  const payload = await response.json()
  points.value = payload.items ?? []
  exceedTotal.value = payload.exceed_total ?? 0
  ledgerTotal.value = points.value.reduce(
    (sum, point) => sum + Number(point['入账条数'] ?? 0),
    0
  )
  pendingReadingCount.value = batches.value
    .filter((batch) => batch.状态 === '待核')
    .reduce((sum, batch) => sum + batch.通过数 + batch.退回数, 0)
}

async function loadBatches(selectId?: number | null) {
  const response = await request('/api/dust/batches')
  if (!response.ok) {
    flash('批次列表读取失败', false)
    return
  }
  const payload = await response.json()
  batches.value = payload.items ?? []
  pendingReadingCount.value = batches.value
    .filter((batch) => batch.状态 === '待核')
    .reduce((sum, batch) => sum + batch.通过数 + batch.退回数, 0)
  if (selectId !== undefined && selectId !== null) {
    selectedBatchId.value = selectId
    await openBatch(selectId)
  } else if (selectedBatchId.value !== null) {
    await openBatch(selectedBatchId.value)
  }
}

async function openBatch(batchId: number) {
  selectedBatchId.value = batchId
  const response = await request(`/api/dust/batches/${batchId}`)
  if (!response.ok) {
    flash('待核表读取失败', false)
    return
  }
  currentBatch.value = await response.json()
}

function addDraftRow() {
  draftRows.value.push({
    point_code: '',
    period: '',
    pm10: '',
    pm25: '',
    measure: '',
    recorder: '',
  })
}

function parsePaste() {
  const lines = pasteText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  const parsed: ReadingRow[] = []
  for (const line of lines) {
    const cells = line.split(/[,\t]|，/).map((cell) => cell.trim())
    if (cells[0] === '点位编号' || /编号/.test(cells[0] ?? '') && /时段/.test(cells[1] ?? '')) {
      continue
    }
    parsed.push({
      point_code: cells[0] ?? '',
      period: cells[1] ?? '',
      pm10: cells[2] ?? '',
      pm25: cells[3] ?? '',
      measure: cells[4] ?? '',
      recorder: cells[5] ?? '',
    })
  }
  if (!parsed.length) {
    flash('没有解析出有效行，请检查格式', false)
    return
  }
  draftRows.value = parsed
  flash(`已解析 ${parsed.length} 行，确认无误后整理为待核表`)
}

function loadExample() {
  pasteText.value = [
    'D-01,2026-10-02 08:00,96,45,喷淋正常,王强',
    'D-02,2026-10-02 08:00,168,80,未喷淋,李军',
    'D-03,2026-10-02 08:00,,38,覆盖到位,赵敏',
    'D-01,2026-10-02 08:00,96,45,喷淋正常,王强',
  ].join('\n')
  parsePaste()
}

async function submitImport() {
  const rows = draftRows.value.map((row) => ({
    ...row,
    pm10: row.pm10 || null,
    pm25: row.pm25 || null,
  }))
  if (!rows.length) {
    flash('请先录入或粘贴读数', false)
    return
  }
  importing.value = true
  try {
    const response = await request('/api/dust/import', {
      method: 'POST',
      body: JSON.stringify({ rows }),
    })
    const payload = await response.json()
    flash(payload.message, payload.ok)
    if (payload.ok && payload.entry) {
      draftRows.value = []
      pasteText.value = ''
      await loadBatches(Number(payload.entry.id))
    }
  } catch (error) {
    flash(error instanceof Error ? error.message : '导入失败', false)
  } finally {
    importing.value = false
  }
}

async function verifyBatch() {
  if (!currentBatch.value) return
  const response = await request(`/api/dust/batches/${currentBatch.value.id}/verify`, {
    method: 'POST',
    body: '{}',
  })
  const payload = await response.json()
  flash(payload.message, payload.ok)
  await loadBatches(currentBatch.value.id)
}

async function postBatch() {
  if (!currentBatch.value) return
  posting.value = true
  try {
    const response = await request(`/api/dust/batches/${currentBatch.value.id}/post`, {
      method: 'POST',
      body: '{}',
    })
    const payload = await response.json()
    flash(payload.message, payload.ok)
    if (payload.ok) {
      await loadBatches(currentBatch.value.id)
      await loadPoints()
    }
  } catch (error) {
    flash(error instanceof Error ? error.message : '入账失败', false)
  } finally {
    posting.value = false
  }
}

async function discardBatch() {
  if (!currentBatch.value) return
  if (!window.confirm(`确认废弃批次 ${currentBatch.value['批次号']}？读数将不会进入台账。`)) {
    return
  }
  const response = await request(`/api/dust/batches/${currentBatch.value.id}/discard`, {
    method: 'POST',
    body: '{}',
  })
  const payload = await response.json()
  flash(payload.message, payload.ok)
  await loadBatches(payload.ok ? null : currentBatch.value.id)
  if (payload.ok) currentBatch.value = null
}

async function reloadLedger() {
  const params = new URLSearchParams()
  if (ledgerFilter.value.point_code) params.set('point_code', ledgerFilter.value.point_code)
  if (ledgerFilter.value.month) params.set('month', ledgerFilter.value.month)
  if (ledgerFilter.value.only_exceed) params.set('only_exceed', 'true')
  params.set('size', '200')
  const response = await request(`/api/dust/ledger?${params.toString()}`)
  if (!response.ok) {
    flash('台账读取失败', false)
    return
  }
  const payload = await response.json()
  ledgerRows.value = payload.items ?? []
  ledgerTotal.value = payload.total ?? 0
}

function resetLedgerFilter() {
  ledgerFilter.value = { point_code: '', month: '', only_exceed: false }
  void reloadLedger()
}

async function fetchReport(month: string) {
  const response = await request(`/api/dust/monthly-report?month=${encodeURIComponent(month)}`)
  if (!response.ok) throw new Error('月报生成失败')
  return (await response.json()) as {
    month: string
    total: number
    exceed_total: number
    items: Record<string, string | number | boolean | null>[]
    summary: Record<string, string | number | null>[]
  }
}

async function reloadReport() {
  if (!/^\d{4}-\d{2}$/.test(reportMonth.value)) {
    flash('月份格式应为 YYYY-MM，如 2026-09', false)
    return
  }
  try {
    report.value = await fetchReport(reportMonth.value)
  } catch (error) {
    flash(error instanceof Error ? error.message : '月报生成失败', false)
  }
}

function batchBadgeClass(status: string) {
  if (status === '已入账') return 'badge-pass'
  if (status === '已废弃') return 'badge-dup'
  return 'badge-pending'
}

function rowBadgeClass(status: string) {
  if (status === '通过') return 'badge-pass'
  if (status === '退回') return 'badge-reject'
  return 'badge-dup'
}

function rowRowClass(row: StagingRow) {
  if (row['审核状态'] === '退回') return 'row-reject'
  if (row['审核状态'] === '重复忽略') return 'row-dup'
  return ''
}

onMounted(() => {
  void loadBatches()
  void loadPoints()
  void reloadLedger()
  void reloadReport()
})
</script>

<style scoped>
.tab-bar { display: flex; gap: 8px; border-bottom: 1px solid var(--border); margin-bottom: 12px; }
.tab-item {
  border: none; background: none; padding: 8px 14px; cursor: pointer;
  font-size: 14px; color: var(--muted); border-bottom: 2px solid transparent;
}
.tab-item.active { color: var(--brand); border-bottom-color: var(--brand); font-weight: 600; }
.tab-badge {
  display: inline-block; min-width: 18px; padding: 0 5px; margin-left: 4px;
  background: #f04438; color: #fff; border-radius: 9px; font-size: 11px;
}
.form-msg { font-size: 13px; padding: 6px 10px; background: #eef4ff; border-radius: 6px; }
.review-layout { display: grid; grid-template-columns: minmax(360px, 1fr) minmax(480px, 1.2fr); gap: 16px; }
.review-col { min-width: 0; }
.block-title { font-size: 14px; margin: 14px 0 6px; }
.block-hint { font-size: 12px; color: var(--muted); margin: 0 0 6px; }
.paste-box { width: 100%; font-family: ui-monospace, monospace; font-size: 12px; padding: 8px; }
.btn-row { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
.edit-table input { width: 100%; border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; font-size: 12px; }
.num-input { max-width: 70px; }
.batch-active { background: #eef4ff; }
.batch-meta { display: flex; gap: 14px; font-size: 12px; color: var(--muted); margin-bottom: 6px; flex-wrap: wrap; }
.reading-table .note-cell { max-width: 260px; font-size: 12px; }
.measure-note { color: #b54708; }
.cover-note { color: #175cd3; }
.dup-note { color: var(--muted); }
.exceed-note { color: #b42318; }
.exceed-cell { color: #b42318; font-weight: 600; }
.row-reject { background: #fef3f2; }
.row-dup { background: #f5f5f4; color: var(--muted); }
.row-exceed { background: #fffaeb; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.badge-pass { background: #dcfae6; color: #067647; }
.badge-reject { background: #fee4e2; color: #b42318; }
.badge-pending { background: #fef0c7; color: #b54708; }
.badge-dup { background: #e4e7ec; color: #475467; }
.pass-text { color: #067647; }
.danger { color: #b42318; }
.danger-btn { color: #b42318; border-color: #fecdca; }
.stat-value.exceed { color: #b42318; }
.check-item { display: flex; align-items: center; gap: 6px; }
.check-item input { width: auto; }
</style>
