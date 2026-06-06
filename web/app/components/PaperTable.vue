<script setup lang="ts">
import type { GraphNode } from '~/types'

defineProps<{ papers: GraphNode[]; sortKey: string; selectedId?: string | null; hoveredId?: string | null }>()
const emit = defineEmits<{
  (e: 'sort', key: string): void
  (e: 'select', id: string): void
  (e: 'hover', id: string | null): void
}>()
</script>

<template>
  <table class="ptable">
    <thead>
      <tr>
        <th>#</th>
        <th>Title</th>
        <th class="num" @click="emit('sort', 'year')">Year</th>
        <th>Venue</th>
        <th class="num" @click="emit('sort', 'citation_count')">Cites ⇅</th>
        <th class="num" @click="emit('sort', 'relevance')">Rel ⇅</th>
        <th class="num" @click="emit('sort', 'importance')">Importance ⇅</th>
        <th class="num" @click="emit('sort', 'level')">Lvl</th>
        <th>Links</th>
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="(p, i) in papers" :key="p.id" :data-pid="p.id"
        :class="{ 'row-active': p.id === selectedId, 'hover-active': p.id === hoveredId }"
        @click="emit('select', p.id)"
        @mouseenter="emit('hover', p.id)" @mouseleave="emit('hover', null)"
      >
        <td class="num muted">{{ i + 1 }}</td>
        <td class="t-title">{{ p.title }}
          <span v-if="p.top_venue" class="star" title="top venue">★</span>
        </td>
        <td class="num">{{ p.year || '—' }}</td>
        <td>{{ p.venue || '—' }}</td>
        <td class="num">{{ (p.citation_count || 0).toLocaleString() }}</td>
        <td class="num">{{ p.relevance != null ? (p.relevance * 100).toFixed(0) + '%' : '—' }}</td>
        <td class="num">
          <span class="bar" :style="{ width: ((p.importance || 0) * 60) + 'px' }" />
          {{ ((p.importance || 0) * 100).toFixed(0) }}
        </td>
        <td class="num">{{ p.level }}</td>
        <td @click.stop>
          <a v-if="p.pdf_url" :href="p.pdf_url" target="_blank">PDF</a>
          <a v-if="p.external_ids.doi" :href="`https://doi.org/${p.external_ids.doi}`" target="_blank" style="margin-left:8px">DOI</a>
        </td>
      </tr>
    </tbody>
  </table>
</template>
