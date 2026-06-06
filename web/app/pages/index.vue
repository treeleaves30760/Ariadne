<script setup lang="ts">
import type { Candidate, Job } from '~/types'

const api = useApi()
const router = useRouter()

const query = ref('')
const depth = ref(3)
const language = ref('en')
const loading = ref(false)
const creating = ref('')
const error = ref('')
const candidates = ref<Candidate[]>([])
const searched = ref(false)
const recent = ref<Job[]>([])

// recent-map right-click menu + inline rename
const menu = ref<{ job: Job; x: number; y: number } | null>(null)
const confirmingDelete = ref(false)
const editingId = ref<string | null>(null)
const editName = ref('')
const navLock = ref(false)

onMounted(async () => {
  try { recent.value = (await api.listJobs()).slice(0, 8) } catch { /* backend may be down */ }
  document.addEventListener('click', closeMenu)
  document.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeMenu)
  document.removeEventListener('keydown', onKey)
})

/** Display label: custom name → seed title (first 40 chars) → seed id. */
function mapLabel(j: Job): string {
  const name = j.name?.trim()
  if (name) return name
  const t = j.seed_title?.trim()
  if (t) return t.length > 40 ? t.slice(0, 40) + '…' : t
  return String((j.params as any).seed_id)
}

/** Full, untruncated label — for tooltips and as the rename prefill. */
function fullLabel(j: Job): string {
  return j.name?.trim() || j.seed_title?.trim() || String((j.params as any).seed_id)
}

function openJob(j: Job) {
  if (navLock.value || editingId.value) return
  router.push(`/jobs/${j.id}`)
}

function openMenu(e: MouseEvent, j: Job) {
  menu.value = { job: j, x: e.clientX, y: e.clientY }
  confirmingDelete.value = false
}

function closeMenu() {
  menu.value = null
  confirmingDelete.value = false
}

// Briefly ignore row clicks so the click that ends an inline edit doesn't also navigate.
function lockNav() {
  navLock.value = true
  window.setTimeout(() => { navLock.value = false }, 60)
}

async function startRename(j: Job) {
  editName.value = fullLabel(j)
  editingId.value = j.id
  closeMenu()
  await nextTick()
  const el = document.getElementById('rename-' + j.id) as HTMLInputElement | null
  el?.focus()
  el?.select()
}

async function saveRename(j: Job) {
  if (editingId.value !== j.id) return   // guards against blur firing after enter/esc
  editingId.value = null
  lockNav()
  let name = editName.value.trim()
  if (name === (j.seed_title?.trim() || '')) name = ''  // same as the title → keep default
  if (name === (j.name || '')) return                    // nothing changed
  try {
    const updated = await api.renameJob(j.id, name)
    j.name = updated.name ?? null
  } catch (e: any) {
    error.value = e?.message || 'rename failed'
  }
}

function cancelRename() {
  editingId.value = null
  lockNav()
}

async function doDelete(j: Job) {
  closeMenu()
  try {
    await api.deleteJob(j.id)
    recent.value = recent.value.filter(x => x.id !== j.id)
  } catch (e: any) {
    error.value = e?.message || 'delete failed'
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') { closeMenu(); editingId.value = null }
}

async function search() {
  if (!query.value.trim()) return
  loading.value = true; error.value = ''; candidates.value = []; searched.value = false
  try {
    const res = await api.resolve(query.value.trim(), 12)
    candidates.value = res.candidates
    searched.value = true
  } catch (e: any) {
    error.value = e?.message || 'search failed'
  } finally {
    loading.value = false
  }
}

async function pick(c: Candidate) {
  creating.value = c.id; error.value = ''
  try {
    const job = await api.createJob({
      seed_id: c.id,
      depth: depth.value,
      language: language.value,
    })
    router.push(`/jobs/${job.id}`)
  } catch (e: any) {
    error.value = e?.message || 'failed to start job'
    creating.value = ''
  }
}
</script>

<template>
  <div class="container">
    <h1>Map the literature around a paper</h1>
    <p class="subtitle">
      Enter a paper title, DOI, arXiv id, or benchmark name. We expand its references and
      citations to depth {{ depth }}, use Codex to keep what's relevant, and write short
      explanations — with a fresh report at each level so you never miss a key paper.
    </p>

    <div class="card">
      <label>Paper / benchmark</label>
      <input
        v-model="query" type="text" placeholder="e.g. Attention Is All You Need, or 10.48550/arXiv.1706.03762"
        @keyup.enter="search"
      />
      <div class="row" style="margin-top: 6px">
        <div>
          <label>Expansion depth</label>
          <select v-model.number="depth">
            <option :value="3">3 — report at L3 + final</option>
            <option :value="4">4 — reports at L3, L4 + final</option>
            <option :value="5">5 — reports at L3–L5 + final</option>
          </select>
        </div>
        <div>
          <label>Summary / report language</label>
          <select v-model="language">
            <option value="en">English</option>
            <option value="zh">繁體中文</option>
            <option value="bilingual">中英對照</option>
          </select>
        </div>
        <div style="display:flex; align-items:flex-end">
          <button class="btn" style="width:100%" :disabled="loading || !query.trim()" @click="search">
            <span v-if="loading" class="spinner" /> {{ loading ? 'Searching…' : 'Search' }}
          </button>
        </div>
      </div>
    </div>

    <p v-if="error" class="error" style="margin-top:16px">{{ error }}</p>

    <div v-if="!searched && recent.length" class="recent">
      <h2>Recent maps <span class="muted" style="font-weight:400;font-size:13px">— right-click to rename or delete</span></h2>
      <div
        v-for="j in recent" :key="j.id" class="job-row"
        @click="openJob(j)" @contextmenu.prevent="openMenu($event, j)"
      >
        <div class="job-main">
          <input
            v-if="editingId === j.id" :id="'rename-' + j.id" v-model="editName" class="rename-input"
            @click.stop @keyup.enter="saveRename(j)" @keyup.esc="cancelRename" @blur="saveRename(j)"
          />
          <div v-else class="job-name" :title="fullLabel(j)">{{ mapLabel(j) }}</div>
          <div class="muted" style="font-size:12px">
            depth {{ (j.params as any).depth }} · {{ j.progress.nodes }} papers · {{ j.progress.status }}
          </div>
        </div>
        <span class="muted" style="font-size:12px">{{ j.created_at.slice(0, 10) }}</span>
      </div>
    </div>

    <template v-if="searched">
      <h2>Pick the seed paper <span class="muted" style="font-weight:400">({{ candidates.length }} candidates)</span></h2>
      <p v-if="!candidates.length" class="muted">No matches found. Try a different query.</p>
      <div
        v-for="c in candidates" :key="c.id" class="candidate"
        @click="pick(c)"
      >
        <div>
          <div>{{ c.title }}</div>
          <div class="meta">
            {{ c.authors.slice(0, 3).join(', ') }}{{ c.authors.length > 3 ? ' et al.' : '' }}
            <template v-if="c.year"> · {{ c.year }}</template>
            <template v-if="c.venue"> · {{ c.venue }}</template>
            <span class="pill src" style="margin-left:8px">{{ c.source }}</span>
          </div>
        </div>
        <div style="text-align:right">
          <div class="cites">{{ (c.citation_count || 0).toLocaleString() }} cites</div>
          <div v-if="creating === c.id" class="muted" style="font-size:12px;margin-top:6px">
            <span class="spinner" /> starting…
          </div>
        </div>
      </div>
    </template>

    <div
      v-if="menu" class="ctx-menu"
      :style="{ top: menu.y + 'px', left: menu.x + 'px' }"
      @click.stop
    >
      <button class="ctx-item" @click="startRename(menu.job)">Rename</button>
      <button v-if="!confirmingDelete" class="ctx-item danger" @click="confirmingDelete = true">Delete</button>
      <button v-else class="ctx-item danger" @click="doDelete(menu.job)">Click again to confirm</button>
    </div>
  </div>
</template>
