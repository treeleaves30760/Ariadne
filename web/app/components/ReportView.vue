<script setup lang="ts">
import type { GraphNode, Report } from '~/types'

const props = defineProps<{ report: Report; nodes: GraphNode[] }>()

const titleOf = (id: string) => {
  const n = props.nodes.find((x) => x.id === id)
  return n ? n.title : id
}
</script>

<template>
  <div class="report">
    <p class="overview">{{ report.overview }}</p>

    <h3 v-if="report.must_reads.length">⭐ Must-read</h3>
    <ul class="gaps" v-if="report.must_reads.length">
      <li v-for="id in report.must_reads" :key="id">{{ titleOf(id) }}</li>
    </ul>

    <h3 v-if="report.clusters.length">Themes</h3>
    <div v-for="(c, i) in report.clusters" :key="i" class="cluster">
      <div class="theme">{{ c.theme }}</div>
      <div class="muted" style="font-size:13px;margin-top:4px">{{ c.summary }}</div>
      <ul>
        <li v-for="id in c.paper_ids" :key="id">{{ titleOf(id) }}</li>
      </ul>
    </div>

    <h3 v-if="report.gaps.length">Research gaps & directions</h3>
    <ul class="gaps" v-if="report.gaps.length">
      <li v-for="(g, i) in report.gaps" :key="i">{{ g }}</li>
    </ul>
  </div>
</template>
