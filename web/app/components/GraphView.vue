<script setup lang="ts">
import type { GraphData } from '~/types'

const props = defineProps<{ data: GraphData }>()
const emit = defineEmits<{ (e: 'select', id: string): void }>()

const el = ref<HTMLElement | null>(null)
const tip = ref<{ show: boolean; x: number; y: number; text: string }>({ show: false, x: 0, y: 0, text: '' })
const layoutMode = ref<'levels' | 'force'>('levels')
const showLabels = ref(true)
let cy: any = null

function elements(data: GraphData) {
  const nodeIds = new Set(data.nodes.map((n) => n.id))
  const nodes = data.nodes.map((n) => ({
    data: {
      id: n.id,
      label: n.title.length > 40 ? n.title.slice(0, 38) + '…' : n.title,
      full: n.title,
      level: n.level,
      rel: n.relevance ?? 0.5,
      seed: n.level === 0 ? 1 : 0,
    },
  }))
  const edges = data.edges
    .filter((e) => nodeIds.has(e.src) && nodeIds.has(e.dst))
    .map((e, i) => ({ data: { id: `e${i}`, source: e.src, target: e.dst, dir: e.direction } }))
  return [...nodes, ...edges]
}

function layoutOpts() {
  if (layoutMode.value === 'levels') {
    return {
      name: 'concentric',
      concentric: (n: any) => 100 - n.data('level') * 20, // seed (level 0) in the centre
      levelWidth: () => 1,
      minNodeSpacing: 26,
      padding: 24,
      animate: false,
    }
  }
  return { name: 'cose', animate: false, padding: 30, nodeRepulsion: 12000, idealEdgeLength: 110, nestingFactor: 1.1 }
}

async function render() {
  if (!import.meta.client || !el.value) return
  const cytoscape = (await import('cytoscape')).default
  if (cy) cy.destroy()
  cy = cytoscape({
    container: el.value,
    elements: elements(props.data),
    minZoom: 0.2,
    maxZoom: 3,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': (n: any) =>
            n.data('seed') ? '#f7768e' : `hsl(${214 - n.data('rel') * 8}, 85%, ${58 + n.data('rel') * 8}%)`,
          width: (n: any) => 12 + n.data('rel') * 16 + (n.data('seed') ? 10 : 0),
          height: (n: any) => 12 + n.data('rel') * 16 + (n.data('seed') ? 10 : 0),
          label: 'data(label)',
          color: '#dbe4ee',
          'font-size': 7,
          'min-zoomed-font-size': 7, // hide labels when zoomed out so they never become unreadable
          'text-wrap': 'wrap',
          'text-max-width': '80px',
          'text-valign': 'bottom',
          'text-margin-y': 2,
          'text-outline-width': 2,
          'text-outline-color': '#0e1116',
          'border-width': (n: any) => (n.data('seed') ? 3 : 0),
          'border-color': '#ffd4dc',
          'transition-property': 'opacity, border-width',
          'transition-duration': 150,
        },
      },
      {
        selector: 'edge',
        style: {
          width: 1.2,
          'line-color': (e: any) => (e.data('dir') === 'reference' ? '#f0a868' : '#5ec8a6'),
          'target-arrow-color': (e: any) => (e.data('dir') === 'reference' ? '#f0a868' : '#5ec8a6'),
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.65,
          'curve-style': 'bezier',
          opacity: 0.45,
        },
      },
      { selector: '.faded', style: { opacity: 0.12, 'text-opacity': 0.12 } },
      { selector: '.highlight', style: { 'border-width': 3, 'border-color': '#6ea8fe' } },
      { selector: 'node.nolabels', style: { label: '' } },
    ],
    layout: layoutOpts(),
    wheelSensitivity: 0.6,
  })

  cy.on('tap', 'node', (evt: any) => {
    emit('select', evt.target.id())
    highlightNeighborhood(evt.target)
  })
  cy.on('tap', (evt: any) => { if (evt.target === cy) clearHighlight() })
  cy.on('mouseover', 'node', (evt: any) => {
    const p = evt.renderedPosition || evt.target.renderedPosition()
    tip.value = { show: true, x: p.x, y: p.y, text: evt.target.data('full') }
  })
  cy.on('mouseout', 'node', () => { tip.value.show = false })
  cy.on('pan zoom', () => { tip.value.show = false })
}

function highlightNeighborhood(node: any) {
  const hood = node.closedNeighborhood()
  cy.elements().addClass('faded')
  hood.removeClass('faded')
  cy.nodes().removeClass('highlight')
  node.addClass('highlight')
}
function clearHighlight() {
  if (!cy) return
  cy.elements().removeClass('faded')
  cy.nodes().removeClass('highlight')
}
function fit() { cy && cy.fit(undefined, 30) }
function relayout() { cy && cy.layout(layoutOpts()).run() }
function zoomBy(f: number) {
  if (!cy) return
  const level = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * f))
  cy.animate({ zoom: { level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } },
             { duration: 120 })
}
function zoomToSelected() {
  if (!cy) return
  const sel = cy.$('node.highlight')
  if (sel.length) cy.animate({ fit: { eles: sel.closedNeighborhood(), padding: 80 } }, { duration: 200 })
}

watch(layoutMode, relayout)
watch(showLabels, () => {
  if (!cy) return
  cy.nodes().forEach((n: any) => n.toggleClass('nolabels', !showLabels.value))
})
watch(() => props.data, render, { deep: true })
onMounted(render)
onBeforeUnmount(() => cy && cy.destroy())
</script>

<template>
  <div class="graph-wrap">
    <div class="graph-toolbar">
      <div class="seg">
        <button :class="{ active: layoutMode === 'levels' }" @click="layoutMode = 'levels'">Rings by depth</button>
        <button :class="{ active: layoutMode === 'force' }" @click="layoutMode = 'force'">Force</button>
      </div>
      <div class="seg">
        <button @click="zoomBy(0.8)" title="Zoom out">−</button>
        <button @click="zoomBy(1.25)" title="Zoom in">+</button>
      </div>
      <button class="ghost" @click="fit">Fit</button>
      <button class="ghost" @click="zoomToSelected" title="Zoom to selected">Focus</button>
      <button class="ghost" @click="relayout">Re-layout</button>
      <label class="lbl-toggle"><input type="checkbox" v-model="showLabels" /> labels</label>
    </div>
    <div ref="el" id="cy" />
    <div v-if="tip.show" class="cy-tip" :style="{ left: tip.x + 14 + 'px', top: tip.y + 12 + 'px' }">{{ tip.text }}</div>
    <div class="legend">
      <span><i style="background:#f7768e" />seed</span>
      <span><i style="background:#f0a868" />reference (this cites →)</span>
      <span><i style="background:#5ec8a6" />citation (→ cites this)</span>
      <span class="muted">size = relevance · hover for title · click to focus</span>
    </div>
  </div>
</template>
