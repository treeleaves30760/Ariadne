<script setup lang="ts">
import type { Candidate } from '~/types'

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
  </div>
</template>
