<script setup lang="ts">
import type { Settings } from '~/types'

const api = useApi()
const s = ref<Settings | null>(null)
const model = ref<string>('')
const effort = ref<string>('')
const apiBase = ref<string>('')
const apiKey = ref<string>('')
const saving = ref(false)
const saved = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    s.value = await api.getSettings()
    model.value = s.value.model || ''
    effort.value = s.value.reasoning_effort || ''
    apiBase.value = s.value.api_base || ''
  } catch (e: any) { error.value = e?.message || 'failed to load settings' }
})

async function save() {
  saving.value = true; saved.value = false; error.value = ''
  try {
    await api.putSettings({
      model: model.value || null,
      reasoning_effort: effort.value || null,
      api_base: apiBase.value || null,
      api_key: apiKey.value || '',   // blank keeps existing key
    })
    apiKey.value = ''
    s.value = await api.getSettings()
    saved.value = true
  } catch (e: any) {
    error.value = e?.data?.detail || e?.message || 'failed to save'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="container" style="max-width: 720px">
    <NuxtLink to="/" class="muted">← Back</NuxtLink>
    <h1 style="margin-top:10px">Settings</h1>
    <p class="subtitle">Choose the model and reasoning effort, and optionally use your own
      OpenAI-compatible endpoint and key. These apply to relevance filtering, summaries,
      reports, and the Ask chatbot.</p>

    <div class="card" v-if="s">
      <div class="row">
        <div>
          <label>Model</label>
          <select v-model="model">
            <option value="">Default (Codex login)</option>
            <option v-for="m in s.available_models" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div>
          <label>Reasoning effort</label>
          <select v-model="effort">
            <option value="">Default</option>
            <option v-for="e in s.reasoning_efforts" :key="e" :value="e">{{ e }}</option>
          </select>
        </div>
      </div>

      <label>OpenAI API endpoint (optional)</label>
      <input v-model="apiBase" type="text" placeholder="https://api.openai.com/v1" />

      <label>OpenAI API key (optional)</label>
      <input v-model="apiKey" type="password" autocomplete="off"
             :placeholder="s.api_key_set ? `saved (${s.api_key_masked}) — leave blank to keep` : 'sk-…'" />
      <p class="muted" style="font-size:12px;margin-top:6px">
        Stored locally on this machine and sent only to your configured endpoint. Leave blank to
        keep the existing key; without a key, Codex uses your local <code>codex login</code>.
      </p>

      <div style="margin-top:16px; display:flex; gap:12px; align-items:center">
        <button class="btn" :disabled="saving" @click="save">
          <span v-if="saving" class="spinner" /> {{ saving ? 'Saving…' : 'Save' }}
        </button>
        <span v-if="saved" class="muted">✓ saved</span>
        <span v-if="error" class="error">{{ error }}</span>
      </div>
    </div>
    <div v-else class="card muted">Loading…</div>
  </div>
</template>
