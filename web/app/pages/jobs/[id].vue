<script setup lang="ts">
import type { Dimension, GraphData, GraphNode, Job, QAResult, Report } from '~/types'

const route = useRoute()
const api = useApi()
const { render } = useMarkdown()
const id = route.params.id as string

const job = ref<Job | null>(null)
const graph = ref<GraphData>({ nodes: [], edges: [] })
const reports = ref<Record<string, Report>>({})
const reportLevels = ref<string[]>([])
const selectedId = ref<string | null>(null)
const hoveredId = ref<string | null>(null)      // node currently hovered on the graph
const focusDimension = ref<string | null>(null) // dimension filter shared with the graph
const headerCollapsed = ref(false)              // status card collapses once the job finishes
const tab = ref<'map' | 'papers' | 'reports' | 'ask'>('map')
const activeReport = ref<string>('')
const sortKey = ref<'importance' | 'foundational' | 'relevance' | 'citation_count' | 'year' | 'level'>('importance')
const useTools = ref(true)
const liveNotes = ref<string[]>([])
const activity = ref<string[]>([])
let stop: (() => void) | null = null
let ticker: ReturnType<typeof setInterval> | null = null
const conn = ref<'live' | 'reconnecting' | 'stale'>('live')  // SSE liveness
let poll: ReturnType<typeof setInterval> | null = null        // REST fallback when SSE goes stale
const nowTick = ref(Date.now())
const elapsedBase = ref(0)          // progress.elapsed_s from the latest event
const elapsedAt = ref(Date.now())   // wall-clock when elapsedBase was captured
function syncElapsed(v: unknown) {
  if (typeof v === 'number') { elapsedBase.value = v; elapsedAt.value = Date.now() }
}

// Q&A state
const question = ref('')
const asking = ref(false)
const qaHistory = ref<QAResult[]>([])
const qaError = ref('')

const depth = computed(() => Number((job.value?.params as any)?.depth ?? 5))
const status = computed(() => job.value?.progress.status ?? 'queued')
const isTerminal = computed(() => ['completed', 'failed'].includes(status.value))
// Auto-collapse the progress card the moment the job reaches a terminal state.
watch(isTerminal, (t) => { if (t) headerCollapsed.value = true })

// Hover on a graph node → scroll the matching card into view in the left list.
function onHover(cid: string | null) {
  hoveredId.value = cid
  if (!cid || selected.value) return
  nextTick(() => {
    const root = document.querySelector('.map-list')
    const elx = root?.querySelector(`[data-pid="${CSS.escape(cid)}"]`)
    elx?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}
const progressPct = computed(() => {
  const p = job.value?.progress
  if (!p) return 0
  if (status.value === 'completed') return 100
  return Math.min(95, Math.round((p.current_level / (depth.value + 1)) * 100))
})

// Live, ticking elapsed time (synced to backend progress.elapsed_s on each event).
const displayElapsed = computed(() =>
  isTerminal.value ? elapsedBase.value : elapsedBase.value + (nowTick.value - elapsedAt.value) / 1000,
)
function fmtDur(s: number): string {
  const t = Math.max(0, Math.round(s))
  const m = Math.floor(t / 60)
  return m > 0 ? `${m}m ${t % 60}s` : `${t}s`
}
const PHASE_LABELS: Record<string, string> = {
  expand: 'Expanding', fetch: 'Fetching links', score: 'Scoring relevance',
  summarize: 'Summarizing', kept: 'Selecting', report: 'Writing report',
  cluster: 'Organizing dimensions', web: 'Web context',
}
const phaseLabel = computed(() => {
  const p = job.value?.progress.phase
  return p ? (PHASE_LABELS[p] || p) : ''
})
// "Where time is going" — cumulative per-phase seconds, biggest first.
const TIMING_LABELS: Record<string, string> = {
  fetch: 'Fetch links', score: 'Score · Codex', summarize: 'Summaries · Codex',
  report: 'Reports · Codex', cluster: 'Dimensions · Codex', web: 'Web context',
}
const timingRows = computed(() => {
  const t = job.value?.progress.timings || {}
  const entries = (Object.entries(t) as [string, number][]).filter(([, v]) => v > 0)
  const total = entries.reduce((a, [, v]) => a + v, 0) || 1
  return entries.sort((a, b) => b[1] - a[1]).map(([k, v]) => ({
    key: k, label: TIMING_LABELS[k] || k, seconds: v, pct: Math.round((v / total) * 100),
  }))
})
const timedTotal = computed(() => timingRows.value.reduce((a, r) => a + r.seconds, 0))
const notes = computed(() => [...(job.value?.progress.notes ?? []), ...liveNotes.value])
const seedNode = computed(() => graph.value.nodes.find((n) => n.level === 0))
const selected = computed<GraphNode | null>(
  () => graph.value.nodes.find((n) => n.id === selectedId.value) ?? null,
)
const reportLabel = (l: string) => (l === 'web' ? 'Web context' : l === 'final' ? 'Final' : 'Level ' + l)
const titleOf = (cid: string) => graph.value.nodes.find((n) => n.id === cid)?.title ?? cid

// --- AI dimensions + Connected-Papers-style hover preview ---
const dimensions = computed<Dimension[]>(() => graph.value.clusters ?? [])
const dimById = computed(() => new Map(dimensions.value.map((d) => [d.id, d])))
const dimOf = (id?: string | null): Dimension | null => (id ? dimById.value.get(id) ?? null : null)
const nodeById = computed(() => new Map(graph.value.nodes.map((n) => [n.id, n])))

const hoveredNode = computed<GraphNode | null>(() => nodeById.value.get(hoveredId.value ?? '') ?? null)
// The right panel previews whatever you hover; a click "pins" it (selected wins).
const previewNode = computed<GraphNode | null>(() => selected.value ?? hoveredNode.value)
const previewPinned = computed(() => !!selected.value)
const previewTags = computed<Dimension[]>(() =>
  (previewNode.value?.tags ?? []).map((t) => dimById.value.get(t)).filter((d): d is Dimension => !!d),
)
// Citation links touching the previewed paper: 'ref' = it cites them, 'cite' = they cite it.
const neighbors = computed<{ node: GraphNode; kind: 'ref' | 'cite' }[]>(() => {
  const n = previewNode.value
  if (!n) return []
  const out: { node: GraphNode; kind: 'ref' | 'cite' }[] = []
  const seen = new Set<string>()
  for (const e of graph.value.edges) {
    let oid: string | null = null
    let kind: 'ref' | 'cite' = 'ref'
    if (e.src === n.id) { oid = e.dst; kind = 'ref' }
    else if (e.dst === n.id) { oid = e.src; kind = 'cite' }
    if (!oid || seen.has(oid)) continue
    const o = nodeById.value.get(oid)
    if (o) { out.push({ node: o, kind }); seen.add(oid) }
  }
  return out
})
// --- Foundational ranking: which works are most central/canonical for this corpus ---
// Ranked by graph in-degree (how many collected papers cite it) + citations; the seed
// can rank low if it's niche/recent, surfacing the real prerequisites to read first.
const byFoundational = computed(() =>
  [...graph.value.nodes].sort((a, b) => (b.foundational ?? 0) - (a.foundational ?? 0)),
)
const foundationalPapers = computed(() =>
  byFoundational.value.filter((n) => (n.in_degree ?? 0) > 0).slice(0, 8),
)
const topFoundationalIds = computed(() => new Set(foundationalPapers.value.map((n) => n.id)))
const seedRank = computed(() => {
  if (!seedNode.value) return null
  const idx = byFoundational.value.findIndex((n) => n.id === seedNode.value!.id)
  return idx >= 0 ? { rank: idx + 1, total: byFoundational.value.length } : null
})
// True when the seed is clearly not the most central work (others are more foundational).
const seedOutranked = computed(() =>
  !!seedRank.value && seedRank.value.rank > 3 && foundationalPapers.value.length > 0,
)
const foundationalRankOf = (id: string) => {
  const i = foundationalPapers.value.findIndex((n) => n.id === id)
  return i >= 0 ? i + 1 : null
}

// Left-column list, optionally narrowed to the focused dimension.
const listPapers = computed(() =>
  focusDimension.value
    ? sortedPapers.value.filter((p) => p.cluster === focusDimension.value)
    : sortedPapers.value,
)

const sortedPapers = computed(() => {
  const k = sortKey.value
  return [...graph.value.nodes].sort((a, b) => {
    const av = (a as any)[k] ?? -1, bv = (b as any)[k] ?? -1
    return bv - av
  })
})
function setSort(k: typeof sortKey.value) { sortKey.value = k }

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
    const res = await api.ask(id, question.value.trim(), useTools.value)
    qaHistory.value.push(res)
    question.value = ''
  } catch (e: any) {
    qaError.value = e?.data?.detail || e?.message || 'failed to answer'
  } finally {
    asking.value = false
  }
}
function gotoPaper(cid: string) { selectedId.value = cid; tab.value = 'map' }

onMounted(async () => {
  try { job.value = await api.getJob(id) } catch { /* */ }
  syncElapsed(job.value?.progress.elapsed_s)
  ticker = setInterval(() => { nowTick.value = Date.now() }, 1000)
  await refreshGraph(); await refreshReports()
  try { qaHistory.value = await api.getQa(id) } catch { /* */ }

  if (job.value && !isTerminal.value) openStream()
})

function stripType(d: any) { const { type, ...rest } = d || {}; return rest }

async function handleEvent(type: string, data: any) {
  // Any genuine event from the server (incl. heartbeat) means the job is alive.
  if (type !== 'reconnecting' && type !== 'stale') conn.value = 'live'
  syncElapsed((data as any)?.elapsed_s)
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
  if (type === 'clusters_ready' || type === 'links_ready') await refreshGraph()
  if (type === 'reconnecting') conn.value = 'reconnecting'
  if (type === 'stale') { conn.value = 'stale'; startPolling() }
  // 'end' = the job reached a terminal state between events (caught on a heartbeat);
  // re-fetch so the status pill + graph reflect the real final state.
  if (['done', 'failed', 'end'].includes(type)) {
    if (type === 'done' && job.value) job.value.progress.status = 'completed'
    if (type === 'failed' && job.value) job.value.progress.status = 'failed'
    await refreshGraph(); await refreshReports()
    job.value = await api.getJob(id).catch(() => job.value)
  }
}
function openStream() { if (stop) stop(); stop = api.streamEvents(id, handleEvent) }
// SSE gave up (stale) → poll the REST endpoint until the job reaches a terminal state.
function startPolling() {
  if (poll) return
  poll = setInterval(async () => {
    const j = await api.getJob(id).catch(() => null)
    if (!j) return
    job.value = j
    syncElapsed(j.progress.elapsed_s)
    if (isTerminal.value) {
      conn.value = 'live'
      await refreshGraph(); await refreshReports()
      if (poll) { clearInterval(poll); poll = null }
    }
  }, 4000)
}
// Manual retry from the "connection lost" banner: drop polling and reopen the stream.
function reconnect() {
  if (poll) { clearInterval(poll); poll = null }
  conn.value = 'reconnecting'
  openStream()
}
onBeforeUnmount(() => { if (stop) stop(); if (ticker) clearInterval(ticker); if (poll) clearInterval(poll) })
</script>

<template>
  <div class="container job-page" style="max-width: 1480px">
    <NuxtLink to="/" class="muted">← New search</NuxtLink>
    <h1 style="margin-top:10px">{{ seedNode?.title || 'Building citation map…' }}</h1>

    <div class="card statuscard" :class="{ collapsed: headerCollapsed && isTerminal }" style="margin-top:8px">
      <div class="status-head">
        <div class="status-lead">
          <span class="pill" :class="{ ok: status === 'completed', bad: status === 'failed' }">{{ status }}</span>
          <span v-if="!isTerminal && phaseLabel" class="pill phase">{{ phaseLabel }}</span>
          <span class="muted status-msg">{{ job?.progress.message }}</span>
          <span v-if="displayElapsed > 0" class="muted elapsed">⏱ {{ fmtDur(displayElapsed) }}</span>
          <span v-if="headerCollapsed && isTerminal" class="status-sum muted">
            · {{ job?.progress.nodes ?? 0 }} papers · {{ job?.progress.edges ?? 0 }} links ·
            depth {{ job?.progress.current_level ?? 0 }}/{{ depth }} ·
            {{ job?.progress.codex_calls ?? 0 }} Codex calls ·
            {{ fmtDur(displayElapsed) }}
          </span>
        </div>
        <div class="status-actions">
          <a class="btn secondary sm" :href="api.exportUrl(id, 'markdown')" target="_blank">Export .md</a>
          <a class="btn secondary sm" :href="api.exportUrl(id, 'bibtex')" target="_blank">Export .bib</a>
          <button v-if="isTerminal" class="chev" :title="headerCollapsed ? 'Show details' : 'Collapse'"
            @click="headerCollapsed = !headerCollapsed">{{ headerCollapsed ? '⌄' : '⌃' }}</button>
        </div>
      </div>

      <div v-if="!(headerCollapsed && isTerminal)">
        <div class="progress-bar"><div :style="{ width: progressPct + '%' }" /></div>
        <div class="stats">
          <div class="stat"><div class="n">{{ job?.progress.nodes ?? 0 }}</div><div class="l">papers</div></div>
          <div class="stat"><div class="n">{{ job?.progress.edges ?? 0 }}</div><div class="l">links</div></div>
          <div class="stat"><div class="n">{{ job?.progress.current_level ?? 0 }}/{{ depth }}</div><div class="l">depth</div></div>
          <div class="stat"><div class="n">{{ job?.progress.codex_calls ?? 0 }}</div><div class="l">Codex calls</div></div>
        </div>

        <!-- where time is going: cumulative per-phase breakdown -->
        <div v-if="timingRows.length" class="timing">
          <div class="timing-head muted">
            Where time is going{{ isTerminal ? '' : ' (so far)' }} · total {{ fmtDur(timedTotal) }}
          </div>
          <div v-for="r in timingRows" :key="r.key" class="timing-row">
            <span class="timing-label">{{ r.label }}</span>
            <span class="timing-bar"><i :style="{ width: r.pct + '%' }" /></span>
            <span class="timing-val muted">{{ fmtDur(r.seconds) }} · {{ r.pct }}%</span>
          </div>
        </div>

        <!-- live activity line -->
        <div v-if="!isTerminal && activity.length" class="muted" style="margin-top:10px;font-size:13px">
          <span class="spinner" /> {{ activity[0] }}
        </div>
      </div>
      <p v-if="!isTerminal && conn === 'reconnecting'" class="muted" style="margin-top:10px">
        <span class="spinner" /> Reconnecting… (the job is still running on the server)
      </p>
      <p v-if="!isTerminal && conn === 'stale'" style="margin-top:10px;color:#d9a441">
        ⚠ Live connection lost — polling for status. If this persists, the job may have stopped.
        <button class="btn secondary sm" style="margin-left:8px" @click="reconnect">Reconnect</button>
      </p>
      <p v-if="job?.error" class="error" style="margin-top:10px">{{ job.error }}</p>
    </div>

    <div class="tabs">
      <div class="tab" :class="{ active: tab === 'map' }" @click="tab = 'map'">Map</div>
      <div class="tab" :class="{ active: tab === 'papers' }" @click="tab = 'papers'">
        Papers <span v-if="graph.nodes.length" class="muted">({{ graph.nodes.length }})</span>
      </div>
      <div class="tab" :class="{ active: tab === 'reports' }" @click="tab = 'reports'">
        Reports <span v-if="reportLevels.length" class="muted">({{ reportLevels.length }})</span>
      </div>
      <div class="tab" :class="{ active: tab === 'ask' }" @click="tab = 'ask'">Ask the literature</div>
    </div>

    <!-- MAP: list (left) · graph (centre) · live detail (right) — Connected-Papers style -->
    <div v-show="tab === 'map'" class="map3">
      <!-- LEFT: paper list -->
      <div class="card panel-col map-list">
        <div class="list-head">
          <strong>Papers <span class="muted" style="font-weight:400">({{ listPapers.length
            }}<template v-if="focusDimension">/{{ graph.nodes.length }}</template>)</span></strong>
          <select v-model="sortKey" class="sortsel" title="sort by">
            <option value="importance">importance</option>
            <option value="foundational">foundational</option>
            <option value="relevance">relevance</option>
            <option value="citation_count">citations</option>
            <option value="year">year</option>
            <option value="level">level</option>
          </select>
        </div>
        <div v-if="focusDimension" class="filter-note">
          <i class="sw" :style="{ background: dimOf(focusDimension)?.color }" />
          {{ dimOf(focusDimension)?.label }}
          <a class="muted clearx" @click="focusDimension = null">clear ✕</a>
        </div>

        <div v-if="!graph.nodes.length" class="muted">No papers yet.</div>
        <div v-else class="pcards">
          <div
            v-for="(p, i) in listPapers" :key="p.id" class="pcard mini"
            :class="{ 'hover-active': p.id === hoveredId, 'sel-active': p.id === selectedId }"
            :data-pid="p.id"
            @click="selectedId = p.id === selectedId ? null : p.id"
            @mouseenter="hoveredId = p.id" @mouseleave="hoveredId = null"
          >
            <div class="pc-title">
              <i v-if="dimOf(p.cluster)" class="cdot" :style="{ background: dimOf(p.cluster)!.color }" :title="dimOf(p.cluster)!.label" />
              {{ i + 1 }}. {{ p.title }}
              <span v-if="p.top_venue" class="star" title="top venue">★</span>
            </div>
            <div class="pc-meta muted">
              {{ p.year || '—' }} · {{ (p.citation_count || 0).toLocaleString() }} cites · imp {{ ((p.importance || 0) * 100).toFixed(0) }}
            </div>
          </div>
        </div>

        <!-- live activity + notes while the job runs -->
        <div v-if="!isTerminal && activity.length" class="qa-history">
          <h3>Live activity</h3>
          <div class="feed">
            <div v-for="(a, i) in activity.slice(0, 10)" :key="i" class="row-line">{{ a }}</div>
          </div>
        </div>
        <div v-if="notes.length" style="margin-top:14px">
          <h3>Notes</h3>
          <div v-for="(n, i) in notes.slice(-6)" :key="i" class="kv">· {{ n }}</div>
        </div>
      </div>

      <!-- CENTRE: graph -->
      <div class="map-graph">
        <ClientOnly>
          <GraphView
            v-if="graph.nodes.length" :data="graph" :selected-id="selectedId" :hovered-id="hoveredId"
            v-model:focus-dim="focusDimension"
            @select="selectedId = $event" @hover="onHover"
          />
          <div v-else class="card muted">Graph will appear as papers are collected…</div>
        </ClientOnly>
      </div>

      <!-- RIGHT: live detail (hover) · pinned (click) · dimensions overview -->
      <div class="card panel map-detail">
        <template v-if="previewNode">
          <div class="detail-head">
            <span v-if="previewPinned" class="pill pinned">📌 pinned</span>
            <span v-else class="pill preview-pill">preview</span>
            <a v-if="previewPinned" class="muted backlink" @click="selectedId = null">unpin ✕</a>
            <span v-else class="muted tiny">hover to browse · click to pin</span>
          </div>
          <div class="ptitle">{{ previewNode.title }}</div>
          <div class="kv">
            {{ previewNode.authors.slice(0, 6).join(', ') }}
            <template v-if="previewNode.year"> · {{ previewNode.year }}</template>
          </div>
          <div v-if="previewNode.venue" class="kv venue">{{ previewNode.venue }}</div>

          <div v-if="dimOf(previewNode.cluster) || previewTags.length" class="dim-row">
            <span v-if="dimOf(previewNode.cluster)" class="dim-tag primary"
              :style="{ borderColor: dimOf(previewNode.cluster)!.color, color: dimOf(previewNode.cluster)!.color }">
              <i class="sw" :style="{ background: dimOf(previewNode.cluster)!.color }" />{{ dimOf(previewNode.cluster)!.label }}
            </span>
            <span v-for="t in previewTags" :key="t.id" class="dim-tag sm"
              :style="{ borderColor: t.color, color: t.color }">{{ t.label }}</span>
          </div>

          <div class="kv chips">
            <span class="pill">level {{ previewNode.level }}</span>
            <span v-if="foundationalRankOf(previewNode.id)" class="pill found">🏛 foundational #{{ foundationalRankOf(previewNode.id) }}</span>
            <span v-if="(previewNode.in_degree ?? 0) > 0" class="pill cite-in" title="papers in this map that cite it">cited by {{ previewNode.in_degree }} here</span>
            <span v-if="previewNode.relevance != null" class="pill">relevance {{ (previewNode.relevance * 100).toFixed(0) }}%</span>
            <span v-if="previewNode.citation_count != null" class="pill">{{ previewNode.citation_count.toLocaleString() }} cites</span>
            <span v-if="previewNode.importance != null" class="pill">importance {{ (previewNode.importance * 100).toFixed(0) }}</span>
            <span v-if="previewNode.top_venue" class="pill star">★ top venue</span>
          </div>

          <div v-if="previewNode.summary" class="summary">{{ previewNode.summary }}</div>
          <div v-if="previewNode.reason" class="reason">Why kept: {{ previewNode.reason }}</div>

          <div class="kv links">
            <a v-if="previewNode.pdf_url" :href="previewNode.pdf_url" target="_blank">📄 PDF ↗</a>
            <a v-if="previewNode.external_ids.doi" :href="`https://doi.org/${previewNode.external_ids.doi}`" target="_blank">DOI ↗</a>
            <a v-if="previewNode.external_ids.arxiv" :href="`https://arxiv.org/abs/${previewNode.external_ids.arxiv}`" target="_blank">arXiv ↗</a>
          </div>

          <div v-if="neighbors.length" class="connections">
            <h3>Connections <span class="muted" style="font-weight:400">({{ neighbors.length }})</span></h3>
            <div
              v-for="c in neighbors.slice(0, 60)" :key="c.node.id" class="conn" :data-pid="c.node.id"
              @click="selectedId = c.node.id"
              @mouseenter="hoveredId = c.node.id" @mouseleave="hoveredId = null"
            >
              <span class="conn-dir" :class="c.kind"
                :title="c.kind === 'ref' ? 'this paper cites it' : 'it cites this paper'">{{ c.kind === 'ref' ? '→' : '←' }}</span>
              <span class="conn-title">{{ c.node.title }}</span>
            </div>
          </div>
        </template>

        <!-- default: foundational papers + dimensions overview -->
        <template v-else>
          <!-- Foundational / "read these first" — ranked by in-corpus citations -->
          <div v-if="foundationalPapers.length" class="founds">
            <div class="list-head">
              <strong>🏛 Foundational <span class="muted" style="font-weight:400">· read these first</span></strong>
            </div>
            <p v-if="seedOutranked" class="muted founds-hint">
              Your starting paper ranks <strong>#{{ seedRank!.rank }}</strong> of {{ seedRank!.total }}
              by how foundational it is here — the works below are cited more <em>within this map</em>
              and may be more essential baselines to read first.
            </p>
            <p v-else class="muted founds-hint">Most-cited works <em>within this map</em> — likely the core baselines.</p>
            <div class="founds-list">
              <div
                v-for="(p, i) in foundationalPapers" :key="p.id" class="frow" :data-pid="p.id"
                :class="{ 'hover-active': p.id === hoveredId, isseed: p.level === 0 }"
                @click="selectedId = p.id"
                @mouseenter="hoveredId = p.id" @mouseleave="hoveredId = null"
              >
                <span class="frank">{{ i + 1 }}</span>
                <div class="fbody">
                  <div class="ftitle">{{ p.title }}<span v-if="p.level === 0" class="seedtag">your seed</span></div>
                  <div class="fmeta muted">cited by {{ p.in_degree }} here · {{ (p.citation_count || 0).toLocaleString() }} total</div>
                </div>
              </div>
            </div>
          </div>

          <div class="list-head" :style="foundationalPapers.length ? 'margin-top:18px' : ''">
            <strong>Dimensions <span v-if="dimensions.length" class="muted" style="font-weight:400">({{ dimensions.length }})</span></strong>
          </div>
          <p class="muted dims-intro">Hover any node to preview it here. The AI organized the map into these dimensions — click one to filter.</p>
          <div v-if="!dimensions.length" class="muted">
            Dimensions appear once the AI finishes organizing the map (after the final report).
          </div>
          <div v-else class="dims">
            <div
              v-for="d in dimensions" :key="d.id" class="dimrow" :class="{ active: focusDimension === d.id }"
              @click="focusDimension = focusDimension === d.id ? null : d.id"
            >
              <div class="dimrow-head">
                <i class="sw" :style="{ background: d.color }" />
                <strong>{{ d.label }}</strong>
                <span class="ct muted">{{ d.paper_ids.length }}</span>
              </div>
              <div v-if="d.description" class="dimrow-desc muted">{{ d.description }}</div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- PAPERS TAB (standalone full table) -->
    <div v-show="tab === 'papers'">
      <div v-if="!graph.nodes.length" class="card muted">No papers yet.</div>
      <div v-else class="card" style="overflow:auto; max-height: 70vh">
        <PaperTable
          :papers="sortedPapers" :sort-key="sortKey" :selected-id="selectedId"
          @sort="setSort" @select="gotoPaper"
        />
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
          Chat with the literature — answers are grounded in the collected corpus (with clickable
          citations) and, when tools are on, verified with web search and by reading open-access
          PDFs. Follow-up questions keep the conversation context.
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
        <div class="tools-row">
          <label class="lbl-toggle"><input type="checkbox" v-model="useTools" /> use tools (web search + read PDFs)</label>
          <span class="muted" style="font-size:12px">tools improve accuracy but take longer</span>
        </div>
        <p v-if="qaError" class="error">{{ qaError }}</p>

        <div class="qa-history">
          <div v-for="(qa, i) in [...qaHistory].reverse()" :key="i" class="qa-answer">
            <div class="qa-q">Q: {{ qa.question }}</div>
            <div class="a-body md" v-html="render(qa.answer)" />
            <div class="qa-cites" v-if="qa.citations.length">
              <span v-for="cid in qa.citations" :key="cid" class="chip" @click="gotoPaper(cid)">{{ titleOf(cid) }}</span>
            </div>
            <div class="tools-row">
              <span class="conf">confidence {{ (qa.confidence * 100).toFixed(0) }}%</span>
              <span v-for="t in (qa.tools_used || [])" :key="t" class="badge">{{ t === 'web' ? '🌐 web' : '📄 pdf' }}</span>
            </div>
            <div v-if="qa.sources && qa.sources.length" class="sources" style="margin-top:8px">
              <details>
                <summary class="muted" style="cursor:pointer;font-size:12px">sources used ({{ qa.sources.length }})</summary>
                <div v-for="(sx, j) in qa.sources" :key="j" class="source">
                  <a :href="sx.url" target="_blank" rel="noopener">{{ sx.title }}</a>
                  <div v-if="sx.note" class="note">{{ sx.note }}</div>
                </div>
              </details>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pill.phase { background: #243044; color: #9db4d8; border-color: transparent; }
.elapsed { font-size: 12px; margin-left: 8px; font-variant-numeric: tabular-nums; }
.timing { margin-top: 14px; }
.timing-head { font-size: 12px; margin-bottom: 6px; }
.timing-row {
  display: grid; grid-template-columns: 130px 1fr auto;
  align-items: center; gap: 10px; margin: 4px 0; font-size: 12px;
}
.timing-label { color: #cfd6e4; white-space: nowrap; }
.timing-bar { background: #1b2230; border-radius: 4px; height: 7px; overflow: hidden; }
.timing-bar i { display: block; height: 100%; background: linear-gradient(90deg, #5b8def, #a06bd8); }
.timing-val { font-variant-numeric: tabular-nums; white-space: nowrap; }

/* ---- Connected-Papers 3-column map: list · graph · detail ---- */
.map3 {
  display: grid;
  grid-template-columns: minmax(220px, 264px) minmax(0, 1fr) minmax(290px, 366px);
  gap: 14px; align-items: start;
}
@media (max-width: 1200px) { .map3 { grid-template-columns: 1fr; } }
.map-graph { min-width: 0; }
.map-list, .map-detail { max-height: 720px; overflow: auto; }
.map-detail.panel { position: sticky; top: 76px; }
.map-list .list-head { gap: 8px; }
.sortsel { width: auto; padding: 4px 8px; font-size: 12px; }

.filter-note {
  display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text);
  background: var(--bg-3); border: 1px solid var(--border); border-radius: 8px;
  padding: 5px 9px; margin-bottom: 9px;
}
.filter-note .sw { width: 10px; height: 10px; border-radius: 3px; }
.filter-note .clearx { margin-left: auto; cursor: pointer; }
.filter-note .clearx:hover { color: var(--text); }

/* compact list cards (no summary/links — the right panel shows full detail) */
.pcard.mini { padding: 8px 10px; }
.pcard.mini .pc-title { font-size: 13px; display: flex; align-items: baseline; gap: 5px; }
.pcard.mini .cdot { width: 8px; height: 8px; border-radius: 50%; flex: none; align-self: center; }
.pcard.sel-active { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }

/* right detail panel */
.detail-head { display: flex; align-items: center; gap: 9px; margin-bottom: 8px; }
.detail-head .backlink { margin-left: auto; cursor: pointer; }
.detail-head .backlink:hover { color: var(--text); }
.detail-head .tiny { margin-left: auto; font-size: 11px; }
.pill.pinned { color: #ffd479; border-color: #6a5a2a; }
.pill.preview-pill { color: var(--text-dim); }
.map-detail .venue { font-style: italic; }
.map-detail .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.map-detail .links { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; }

.dim-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 11px; }
.dim-tag {
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600;
  border: 1px solid var(--border); border-radius: 999px; padding: 3px 10px;
}
.dim-tag .sw { width: 9px; height: 9px; border-radius: 3px; }
.dim-tag.sm { font-weight: 500; opacity: 0.85; }

.connections { margin-top: 16px; }
.connections .conn {
  display: flex; align-items: baseline; gap: 8px; padding: 5px 6px; border-radius: 7px;
  cursor: pointer; font-size: 12.5px;
}
.connections .conn:hover { background: var(--bg-3); }
.conn-dir { font-weight: 700; flex: none; width: 12px; text-align: center; }
.conn-dir.ref { color: var(--ref); }
.conn-dir.cite { color: var(--cite); }
.conn-title { color: var(--text); overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }

/* dimensions overview (right panel default state) */
.dims-intro { margin-top: 0; font-size: 12.5px; }
.dims { display: flex; flex-direction: column; gap: 8px; }
.dimrow {
  border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px;
  background: var(--bg-3); cursor: pointer; transition: border-color .12s;
}
.dimrow:hover { border-color: var(--accent); }
.dimrow.active { border-color: var(--text); box-shadow: inset 0 0 0 1px var(--accent-2); }
.dimrow-head { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
.dimrow-head .sw { width: 11px; height: 11px; border-radius: 3px; flex: none; }
.dimrow-head .ct { margin-left: auto; font-variant-numeric: tabular-nums; }
.dimrow-desc { font-size: 12px; margin-top: 5px; line-height: 1.45; }

/* foundational badges + "read these first" panel */
.pill.found { color: #ffd479; border-color: #6a5a2a; background: rgba(255,212,121,0.08); }
.pill.cite-in { color: var(--cite); border-color: #2f6b53; }
.founds-hint { margin-top: 0; font-size: 12.5px; line-height: 1.5; }
.founds-list { display: flex; flex-direction: column; gap: 6px; }
.frow {
  display: flex; gap: 9px; align-items: flex-start; padding: 7px 8px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--bg-3); cursor: pointer; transition: border-color .12s;
}
.frow:hover, .frow.hover-active { border-color: var(--accent); }
.frow.isseed { border-color: var(--seed); background: rgba(247,118,142,0.07); }
.frank {
  flex: none; width: 20px; height: 20px; border-radius: 50%; font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  background: #2a3550; color: #cfe0ff; font-variant-numeric: tabular-nums;
}
.fbody { min-width: 0; }
.ftitle { font-size: 12.5px; font-weight: 600; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.seedtag { font-size: 10px; font-weight: 600; color: var(--seed); border: 1px solid var(--seed);
  border-radius: 999px; padding: 0 6px; margin-left: 6px; white-space: nowrap; }
.fmeta { font-size: 11.5px; margin-top: 2px; font-variant-numeric: tabular-nums; }
</style>
