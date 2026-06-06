<script setup lang="ts">
import type { GraphData } from '~/types'

const props = defineProps<{ data: GraphData; selectedId?: string | null }>()
const emit = defineEmits<{
  (e: 'select', id: string | null): void
  (e: 'hover', id: string | null): void
}>()

// Importance → colour heat (dim slate → blue → vivid violet). Brighter = more important.
const IMP_STOPS: [number, string][] = [[0, '#3a4665'], [0.5, '#5b86d6'], [1, '#b48cff']]
function hexToRgb(h: string) { return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) }
function impColor(t: number): string {
  t = Math.max(0, Math.min(1, t || 0))
  let i = 0
  while (i < IMP_STOPS.length - 1 && t > IMP_STOPS[i + 1][0]) i++
  const [t0, c0] = IMP_STOPS[i]
  const [t1, c1] = IMP_STOPS[Math.min(i + 1, IMP_STOPS.length - 1)]
  const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0)
  const a = hexToRgb(c0), b = hexToRgb(c1)
  const m = a.map((v, k) => Math.round(v + (b[k] - v) * f))
  return `rgb(${m[0]},${m[1]},${m[2]})`
}

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
      imp: n.importance ?? 0.3,
      tv: n.top_venue ? 1 : 0,
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
          // Small circles; importance is encoded by COLOUR (not size).
          'background-color': (n: any) => (n.data('seed') ? '#f7768e' : impColor(n.data('imp'))),
          width: (n: any) => (n.data('seed') ? 16 : 9 + n.data('imp') * 5),
          height: (n: any) => (n.data('seed') ? 16 : 9 + n.data('imp') * 5),
          label: 'data(label)',
          color: '#cfd9e6',
          'font-size': 6.5,
          'min-zoomed-font-size': 8, // hide labels when zoomed out so they never become unreadable
          'text-wrap': 'wrap',
          'text-max-width': '76px',
          'text-valign': 'bottom',
          'text-margin-y': 2,
          'text-outline-width': 2,
          'text-outline-color': '#0e1116',
          // gold ring marks top-venue papers; seed keeps its pink ring
          'border-width': (n: any) => (n.data('seed') ? 2.5 : n.data('tv') ? 1.5 : 0),
          'border-color': (n: any) => (n.data('seed') ? '#ffd4dc' : '#ffd479'),
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
    const tapped = evt.target.id()
    emit('select', tapped === props.selectedId ? null : tapped)  // re-tap toggles off
  })
  cy.on('tap', (evt: any) => { if (evt.target === cy) emit('select', null) })  // empty canvas → deselect
  cy.on('mouseover', 'node', (evt: any) => {
    const p = evt.renderedPosition || evt.target.renderedPosition()
    tip.value = { show: true, x: p.x, y: p.y, text: evt.target.data('full') }
    emit('hover', evt.target.id())   // let the side list scroll to & preview this paper
  })
  cy.on('mouseout', 'node', () => { tip.value.show = false; emit('hover', null) })
  cy.on('pan zoom', () => { tip.value.show = false })
  applySelection(props.selectedId)  // restore highlight after a (re-)render
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
/** Reflect the parent's selection: highlight that node's neighborhood, or clear. */
function applySelection(id: string | null | undefined) {
  if (!cy) return
  const n = id ? cy.getElementById(id) : null
  if (n && n.length) highlightNeighborhood(n)
  else clearHighlight()
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

watch(() => props.selectedId, (id) => applySelection(id))
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
      <span><i class="dot" style="background:#f7768e" />seed</span>
      <span><i class="dot grad" />importance (brighter = higher)</span>
      <span><i class="dot ring" />★ top venue</span>
      <span><i style="background:#f0a868" />reference (this cites →)</span>
      <span><i style="background:#5ec8a6" />citation (→ cites this)</span>
      <span class="muted">hover a node to preview · click to focus</span>
    </div>
  </div>
</template>
