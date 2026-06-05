<script setup lang="ts">
import type { GraphData, GraphNode, Job, Report } from '~/types'

const route = useRoute()
const api = useApi()
const id = route.params.id as string

const job = ref<Job | null>(null)
const graph = ref<GraphData>({ nodes: [], edges: [] })
const reports = ref<Record<string, Report>>({})
const reportLevels = ref<string[]>([])
const selectedId = ref<string | null>(null)
const tab = ref<'graph' | 'reports'>('graph')
const activeReport = ref<string>('')
const notes = ref<string[]>([])
let stop: (() => void) | null = null

const depth = computed(() => Number((job.value?.params as any)?.depth ?? 5))
const status = computed(() => job.value?.progress.status ?? 'queued')
const isTerminal = computed(() => ['completed', 'failed'].includes(status.value))
const progressPct = computed(() => {
  const p = job.value?.progress
  if (!p) return 0
  if (status.value === 'completed') return 100
  return Math.min(95, Math.round((p.current_level / (depth.value + 1)) * 100))
})
const seedNode = computed(() => graph.value.nodes.find((n) => n.level === 0))
const selected = computed<GraphNode | null>(
  () => graph.value.nodes.find((n) => n.id === selectedId.value) ?? null,
)

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

onMounted(async () => {
  try { job.value = await api.getJob(id) } catch { /* */ }
  await refreshGraph()
  await refreshReports()

  if (job.value && !isTerminal.value) {
    stop = api.streamEvents(id, async (type, data) => {
      if (type === 'snapshot' && job.value) job.value.progress = { ...job.value.progress, ...data }
      if (['progress', 'note', 'reporting'].includes(type) && job.value) {
        job.value.progress = { ...job.value.progress, ...stripType(data) }
      }
      if (type === 'note' && data?.message) notes.value.push(data.message)
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
      <p v-if="job?.error" class="error" style="margin-top:10px">{{ job.error }}</p>
    </div>

    <div class="tabs">
      <div class="tab" :class="{ active: tab === 'graph' }" @click="tab = 'graph'">Graph</div>
      <div class="tab" :class="{ active: tab === 'reports' }" @click="tab = 'reports'">
        Reports <span v-if="reportLevels.length" class="muted">({{ reportLevels.length }})</span>
      </div>
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
            <a v-if="selected.external_ids.doi" :href="`https://doi.org/${selected.external_ids.doi}`" target="_blank">DOI ↗</a>
            <a v-if="selected.external_ids.arxiv" :href="`https://arxiv.org/abs/${selected.external_ids.arxiv}`" target="_blank" style="margin-left:12px">arXiv ↗</a>
            <a v-if="selected.url" :href="selected.url" target="_blank" style="margin-left:12px">Source ↗</a>
          </div>
        </template>
        <template v-else>
          <div class="muted">Click a node in the graph to see its details and AI explanation.</div>
          <div v-if="notes.length" style="margin-top:16px">
            <h3>Progress notes</h3>
            <div v-for="(n, i) in notes.slice(-6)" :key="i" class="kv">· {{ n }}</div>
          </div>
        </template>
      </div>
    </div>

    <!-- REPORTS TAB -->
    <div v-show="tab === 'reports'">
      <div v-if="!reportLevels.length" class="card muted">
        Reports are generated from depth 3 onward, plus a final synthesis. None yet.
      </div>
      <template v-else>
        <div class="tabs">
          <div
            v-for="l in reportLevels" :key="l" class="tab" :class="{ active: activeReport === l }"
            @click="activeReport = l"
          >{{ l === 'final' ? 'Final' : 'Level ' + l }}</div>
        </div>
        <div class="card" v-if="reports[activeReport]">
          <ReportView :report="reports[activeReport]" :nodes="graph.nodes" />
        </div>
      </template>
    </div>
  </div>
</template>
