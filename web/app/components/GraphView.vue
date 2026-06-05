<script setup lang="ts">
import type { GraphData } from '~/types'

const props = defineProps<{ data: GraphData }>()
const emit = defineEmits<{ (e: 'select', id: string): void }>()

const el = ref<HTMLElement | null>(null)
let cy: any = null

function elements(data: GraphData) {
  const nodeIds = new Set(data.nodes.map((n) => n.id))
  const nodes = data.nodes.map((n) => ({
    data: {
      id: n.id,
      label: n.title.length > 48 ? n.title.slice(0, 46) + '…' : n.title,
      level: n.level,
      rel: n.relevance ?? 0.5,
      seed: n.level === 0 ? 1 : 0,
    },
  }))
  const edges = data.edges
    .filter((e) => nodeIds.has(e.src) && nodeIds.has(e.dst))
    .map((e, i) => ({
      data: { id: `e${i}`, source: e.src, target: e.dst, dir: e.direction },
    }))
  return [...nodes, ...edges]
}

async function render() {
  if (!import.meta.client || !el.value) return
  const cytoscape = (await import('cytoscape')).default
  if (cy) cy.destroy()
  cy = cytoscape({
    container: el.value,
    elements: elements(props.data),
    style: [
      {
        selector: 'node',
        style: {
          'background-color': (n: any) =>
            n.data('seed') ? '#f7768e' : `rgb(${110 + n.data('rel') * 30}, ${150 + n.data('rel') * 60}, 254)`,
          width: (n: any) => 18 + n.data('rel') * 26 + (n.data('seed') ? 14 : 0),
          height: (n: any) => 18 + n.data('rel') * 26 + (n.data('seed') ? 14 : 0),
          label: 'data(label)',
          color: '#c8d3de',
          'font-size': 8,
          'text-wrap': 'wrap',
          'text-max-width': '90px',
          'text-valign': 'bottom',
          'text-margin-y': 3,
          'border-width': (n: any) => (n.data('seed') ? 3 : 0),
          'border-color': '#ffd4dc',
        },
      },
      {
        selector: 'edge',
        style: {
          width: 1.4,
          'line-color': (e: any) => (e.data('dir') === 'reference' ? '#f0a868' : '#5ec8a6'),
          'target-arrow-color': (e: any) => (e.data('dir') === 'reference' ? '#f0a868' : '#5ec8a6'),
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.7,
          'curve-style': 'bezier',
          opacity: 0.5,
        },
      },
      { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#6ea8fe' } },
    ],
    layout: { name: 'cose', animate: false, padding: 30, nodeRepulsion: 9000, idealEdgeLength: 90 },
    wheelSensitivity: 0.25,
  })
  cy.on('tap', 'node', (evt: any) => emit('select', evt.target.id()))
}

onMounted(render)
watch(() => props.data, render, { deep: true })
onBeforeUnmount(() => cy && cy.destroy())
</script>

<template>
  <div>
    <div ref="el" id="cy" />
    <div class="legend">
      <span><i style="background:#f7768e" />seed</span>
      <span><i style="background:#f0a868" />reference (cited by)</span>
      <span><i style="background:#5ec8a6" />citation (cites this)</span>
      <span class="muted">node size = relevance · click a node for details</span>
    </div>
  </div>
</template>
