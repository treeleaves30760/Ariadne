<script setup lang="ts">
import type { GraphNode, Report } from '~/types'

const props = defineProps<{ report: Report; nodes: GraphNode[] }>()
const emit = defineEmits<{ (e: 'select', id: string): void }>()
const { render } = useMarkdown()

const titleOf = (id: string) => {
  const n = props.nodes.find((x) => x.id === id)
  return n ? n.title : id
}
const host = (url: string) => {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}
</script>

<template>
  <div class="report">
    <div class="md overview" v-html="render(report.overview)" />

    <!-- external web context -->
    <template v-if="report.sources && report.sources.length">
      <h3>🌐 External sources (web)</h3>
      <div class="sources">
        <div v-for="(s, i) in report.sources" :key="i" class="source">
          <a :href="s.url" target="_blank" rel="noopener">{{ s.title }}</a>
          <div class="host">{{ host(s.url) }}</div>
          <div v-if="s.note" class="note">{{ s.note }}</div>
        </div>
      </div>
    </template>

    <h3 v-if="report.must_reads.length">⭐ Must-read</h3>
    <div class="qa-cites" v-if="report.must_reads.length">
      <span v-for="id in report.must_reads" :key="id" class="chip" @click="emit('select', id)">
        {{ titleOf(id) }}
      </span>
    </div>

    <h3 v-if="report.clusters.length">Themes</h3>
    <div v-for="(c, i) in report.clusters" :key="i" class="cluster">
      <div class="theme">{{ c.theme }}</div>
      <div class="md muted" style="font-size:13px;margin-top:4px" v-html="render(c.summary)" />
      <ul>
        <li v-for="id in c.paper_ids" :key="id">
          <a href="#" @click.prevent="emit('select', id)">{{ titleOf(id) }}</a>
        </li>
      </ul>
    </div>

    <h3 v-if="report.gaps.length">Research gaps & directions</h3>
    <ul class="gaps" v-if="report.gaps.length">
      <li v-for="(g, i) in report.gaps" :key="i">{{ g }}</li>
    </ul>
  </div>
</template>
