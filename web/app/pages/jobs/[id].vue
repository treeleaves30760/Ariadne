<script setup lang="ts">
import type { GraphData, GraphNode, Job, QAResult, Report } from '~/types'

const route = useRoute()
const api = useApi()
const { render } = useMarkdown()
const id = route.params.id as string

const job = ref<Job | null>(null)
const graph = ref<GraphData>({ nodes: [], edges: [] })
const reports = ref<Record<string, Report>>({})
const reportLevels = ref<string[]>([])
const selectedId = ref<string | null>(null)
const tab = ref<'graph' | 'reports' | 'ask'>('graph')
const activeReport = ref<string>('')
const liveNotes = ref<string[]>([])
const activity = ref<string[]>([])
let stop: (() => void) | null = null

// Q&A state
const question = ref('')
const asking = ref(false)
const qaHistory = ref<QAResult[]>([])
const qaError = ref('')

const depth = computed(() => Number((job.value?.params as any)?.depth ?? 5))
const status = computed(() => job.value?.progress.status ?? 'queued')
const isTerminal = computed(() => ['completed', 'failed'].includes(status.value))
const progressPct = computed(() => {
  const p = job.value?.progress
  if (!p) return 0
  if (status.value === 'completed') return 100
  return Math.min(95, Math.round((p.current_level / (depth.value + 1)) * 100))
})
const notes = computed(() => [...(job.value?.progress.notes ?? []), ...liveNotes.value])
const seedNode = computed(() => graph.value.nodes.find((n) => n.level === 0))
const selected = computed<GraphNode | null>(
  () => graph.value.nodes.find((n) => n.id === selectedId.value) ?? null,
)
const reportLabel = (l: string) => (l === 'web' ? 'Web context' : l === 'final' ? 'Final' : 'Level ' + l)
const titleOf = (cid: string) => graph.value.nodes.find((n) => n.id === cid)?.title ?? cid

async function refreshGraph() {
  try { graph.value = await api.getGraph(id) } catch { /* not ready */ }
}
async function loadReport(level: string) {
  if (reports.value[level]) return
  try { reports.value[level] = await api.getReport(id, level) } catch { /* */ }
}
async function refreshReports() {
  try {
    const { levels } = await api.listReports(id)
    reportLevels.value = levels
    for (const l of levels) await loadReport(l)
    if (!activeReport.value && levels.length) activeReport.value = levels[levels.length - 1]
  } catch { /* */ }
}

async function ask() {
  if (!question.value.trim() || asking.value) return
  asking.value = true; qaError.value = ''
  try {
    const res = await api.ask(id, question.value.trim())
    qaHistory.value.push(res)
    question.value = ''
  } catch (e: any) {
    qaError.value = e?.data?.detail || e?.message || 'failed to answer'
  } finally {
    asking.value = false
  }
}
function gotoPaper(cid: string) { selectedId.value = cid; tab.value = 'graph' }

onMounted(async () => {
  try { job.value = await api.getJob(id) } catch { /* */ }
  await refreshGraph(); await refreshReports()
  try { qaHistory.value = await api.getQa(id) } catch { /* */ }

  if (job.value && !isTerminal.value) {
    stop = api.streamEvents(id, async (type, data) => {
      if (type === 'snapshot' && job.value) job.value.progress = { ...job.value.progress, ...data }
      if (['progress', 'reporting'].includes(type) && job.value) {
        job.value.progress = { ...job.value.progress, ...stripType(data) }
      }
      if (type === 'activity' && data?.message) {
        activity.value.unshift(data.message)
        if (activity.value.length > 60) activity.value.pop()
      }
      if (type === 'note' && data?.message) liveNotes.value.push(data.message)
      if (type === 'progress' && typeof data?.message === 'string' && data.message.includes('kept')) {
        await refreshGraph()
      }
      if (type === 'report_ready') { await refreshReports(); await refreshGraph() }
      if (type === 'done' || type === 'failed') {
        if (job.value) job.value.progress.status = type === 'done' ? 'completed' : 'failed'
        await refreshGraph(); await refreshReports()
        job.value = await api.getJob(id).catch(() => job.value)
      }
    })
  }
})

function stripType(d: any) { const { type, ...rest } = d || {}; return rest }
onBeforeUnmount(() => stop && stop())
</script>

<template>
  <div class="container" style="max-width: 1180px">
    <NuxtLink to="/" class="muted">← New search</NuxtLink>
    <h1 style="margin-top:10px">{{ seedNode?.title || 'Building citation map…' }}</h1>

    <div class="card" style="margin-top:8px">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap">
        <div>
          <span class="pill">{{ status }}</span>
          <span class="muted" style="margin-left:10px">{{ job?.progress.message }}</span>
        </div>
        <div style="display:flex; gap:8px">
          <a class="btn secondary" :href="api.exportUrl(id, 'markdown')" target="_blank">Export .md</a>
          <a class="btn secondary" :href="api.exportUrl(id, 'bibtex')" target="_blank">Export .bib</a>
        </div>
      </div>
      <div class="progress-bar"><div :style="{ width: progressPct + '%' }" /></div>
      <div class="stats">
        <div class="stat"><div class="n">{{ job?.progress.nodes ?? 0 }}</div><div class="l">papers</div></div>
        <div class="stat"><div class="n">{{ job?.progress.edges ?? 0 }}</div><div class="l">links</div></div>
        <div class="stat"><div class="n">{{ job?.progress.current_level ?? 0 }}/{{ depth }}</div><div class="l">depth</div></div>
        <div class="stat"><div class="n">{{ job?.progress.codex_calls ?? 0 }}</div><div class="l">Codex calls</div></div>
      </div>
      <!-- live activity line -->
      <div v-if="!isTerminal && activity.length" class="muted" style="margin-top:10px;font-size:13px">
        <span class="spinner" /> {{ activity[0] }}
      </div>
      <p v-if="job?.error" class="error" style="margin-top:10px">{{ job.error }}</p>
    </div>

    <div class="tabs">
      <div class="tab" :class="{ active: tab === 'graph' }" @click="tab = 'graph'">Graph</div>
      <div class="tab" :class="{ active: tab === 'reports' }" @click="tab = 'reports'">
        Reports <span v-if="reportLevels.length" class="muted">({{ reportLevels.length }})</span>
      </div>
      <div class="tab" :class="{ active: tab === 'ask' }" @click="tab = 'ask'">Ask the literature</div>
    </div>

    <!-- GRAPH TAB -->
    <div v-show="tab === 'graph'" class="job-layout">
      <div>
        <ClientOnly>
          <GraphView v-if="graph.nodes.length" :data="graph" @select="selectedId = $event" />
          <div v-else class="card muted">Graph will appear as papers are collected…</div>
        </ClientOnly>
      </div>

      <div class="card panel">
        <template v-if="selected">
          <div class="ptitle">{{ selected.title }}</div>
          <div class="kv">
            {{ selected.authors.slice(0, 4).join(', ') }}
            <template v-if="selected.year"> · {{ selected.year }}</template>
          </div>
          <div class="kv">
            <span class="pill">level {{ selected.level }}</span>
            <span v-if="selected.relevance != null" class="pill" style="margin-left:6px">
              relevance {{ (selected.relevance * 100).toFixed(0) }}%
            </span>
            <span v-if="selected.citation_count != null" class="pill" style="margin-left:6px">
              {{ selected.citation_count.toLocaleString() }} cites
            </span>
          </div>
          <div v-if="selected.summary" class="summary">{{ selected.summary }}</div>
          <div v-if="selected.reason" class="reason">Why kept: {{ selected.reason }}</div>
          <div class="kv" style="margin-top:12px">
            <a v-if="selected.pdf_url" :href="selected.pdf_url" target="_blank">📄 Read PDF ↗</a>
            <a v-if="selected.external_ids.doi" :href="`https://doi.org/${selected.external_ids.doi}`" target="_blank" style="margin-left:12px">DOI ↗</a>
            <a v-if="selected.external_ids.arxiv" :href="`https://arxiv.org/abs/${selected.external_ids.arxiv}`" target="_blank" style="margin-left:12px">arXiv ↗</a>
          </div>
        </template>
        <template v-else>
          <div class="muted">Click a node to see its details and AI explanation.</div>
          <div v-if="activity.length" class="qa-history">
            <h3>Live activity</h3>
            <div class="feed">
              <div v-for="(a, i) in activity.slice(0, 12)" :key="i" class="row-line">{{ a }}</div>
            </div>
          </div>
          <div v-if="notes.length" style="margin-top:16px">
            <h3>Notes</h3>
            <div v-for="(n, i) in notes.slice(-8)" :key="i" class="kv">· {{ n }}</div>
          </div>
        </template>
      </div>
    </div>

    <!-- REPORTS TAB -->
    <div v-show="tab === 'reports'">
      <div v-if="!reportLevels.length" class="card muted">
        Reports are generated from depth 3 onward, a final synthesis, and a web-context report. None yet.
      </div>
      <template v-else>
        <div class="tabs">
          <div
            v-for="l in reportLevels" :key="l" class="tab" :class="{ active: activeReport === l }"
            @click="activeReport = l"
          >{{ reportLabel(l) }}</div>
        </div>
        <div class="card" v-if="reports[activeReport]">
          <ReportView :report="reports[activeReport]" :nodes="graph.nodes" @select="gotoPaper" />
        </div>
      </template>
    </div>

    <!-- ASK TAB -->
    <div v-show="tab === 'ask'">
      <div class="card">
        <p class="muted" style="margin-top:0">
          Ask a question about this set of papers — the answer is grounded only in the collected
          corpus, with citations you can click.
        </p>
        <div class="qa-input">
          <input
            v-model="question" type="text"
            placeholder="e.g. What are the main approaches, and where do they disagree?"
            @keyup.enter="ask"
          />
          <button class="btn" :disabled="asking || !question.trim()" @click="ask">
            <span v-if="asking" class="spinner" /> {{ asking ? 'Thinking…' : 'Ask' }}
          </button>
        </div>
        <p v-if="qaError" class="error">{{ qaError }}</p>

        <div class="qa-history">
          <div v-for="(qa, i) in [...qaHistory].reverse()" :key="i" class="qa-answer">
            <div class="qa-q">Q: {{ qa.question }}</div>
            <div class="a-body md" v-html="render(qa.answer)" />
            <div class="qa-cites" v-if="qa.citations.length">
              <span v-for="cid in qa.citations" :key="cid" class="chip" @click="gotoPaper(cid)">{{ titleOf(cid) }}</span>
            </div>
            <div class="conf">confidence {{ (qa.confidence * 100).toFixed(0) }}%</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
