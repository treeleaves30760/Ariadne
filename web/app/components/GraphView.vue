<script setup lang="ts">
import type { GraphData, Dimension } from '~/types'

const props = defineProps<{
  data: GraphData
  selectedId?: string | null
  hoveredId?: string | null
  focusDim?: string | null
}>()
const emit = defineEmits<{
  (e: 'select', id: string | null): void
  (e: 'hover', id: string | null): void
  (e: 'update:focusDim', id: string | null): void
}>()

type ColorMode = 'dimension' | 'importance' | 'year'
type LayoutMode = 'dimensions' | 'force' | 'levels'

const hasClusters = computed(() => (props.data.clusters?.length ?? 0) > 0)

const el = ref<HTMLElement | null>(null)
const tip = ref<{ show: boolean; x: number; y: number; text: string }>({ show: false, x: 0, y: 0, text: '' })
const layoutMode = ref<LayoutMode>('dimensions')
const colorMode = ref<ColorMode>('dimension')
const showLabels = ref(true)
// Focused dimension is owned by the parent (v-model:focus-dim) so the right-panel
// overview, the legend chips, and the on-canvas dimension boxes all agree.
const focusDim = computed<string | null>({
  get: () => props.focusDim ?? null,
  set: (v) => emit('update:focusDim', v),
})
let cy: any = null
let userPickedLayout = false
let userPickedColor = false

// ----------------------------- colour scales ----------------------------- //
const SEED = '#f7768e'
const IMP_STOPS: [number, string][] = [[0, '#3a4665'], [0.5, '#5b86d6'], [1, '#b48cff']]
const YEAR_STOPS: [number, string][] = [[0, '#2b4a63'], [0.5, '#3f9ea6'], [1, '#8be9c0']]
function hexToRgb(h: string) { return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) }
function lerp(stops: [number, string][], t: number): string {
  t = Math.max(0, Math.min(1, t || 0))
  let i = 0
  while (i < stops.length - 1 && t > stops[i + 1][0]) i++
  const [t0, c0] = stops[i]
  const [t1, c1] = stops[Math.min(i + 1, stops.length - 1)]
  const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0)
  const a = hexToRgb(c0), b = hexToRgb(c1)
  const m = a.map((v, k) => Math.round(v + (b[k] - v) * f))
  return `rgb(${m[0]},${m[1]},${m[2]})`
}

const dimColor = computed(() => {
  const m = new Map<string, string>()
  for (const d of props.data.clusters ?? []) m.set(d.id, d.color || '#5b86d6')
  return m
})
const yearRange = computed(() => {
  const ys = props.data.nodes.map((n) => n.year ?? 0).filter((y) => y > 0)
  return ys.length ? [Math.min(...ys), Math.max(...ys)] : [0, 1]
})
const maxLogCites = computed(() => {
  const v = props.data.nodes.map((n) => Math.log1p(n.citation_count ?? 0))
  return Math.max(1, ...v)
})
const maxIndeg = computed(() => Math.max(1, ...props.data.nodes.map((n) => n.in_degree ?? 0)))
// Top foundational works (cited within the corpus) get a distinct ring.
const foundationalIds = computed(() => new Set(
  [...props.data.nodes]
    .filter((n) => (n.in_degree ?? 0) > 0 && n.level !== 0)
    .sort((a, b) => (b.foundational ?? 0) - (a.foundational ?? 0))
    .slice(0, 8)
    .map((n) => n.id),
))

function nodeColor(d: any): string {
  if (d.seed) return SEED
  if (colorMode.value === 'dimension') return dimColor.value.get(d.cluster) || '#4a566b'
  if (colorMode.value === 'year') {
    const [lo, hi] = yearRange.value
    return lerp(YEAR_STOPS, hi === lo ? 1 : ((d.year || lo) - lo) / (hi - lo))
  }
  return lerp(IMP_STOPS, d.imp)
}
function nodeSize(d: any): number {
  if (d.seed) return 22
  // Blend global citations with in-corpus in-degree so foundational hubs read as big.
  const cites = Math.log1p(d.cites || 0) / maxLogCites.value
  const central = (d.indeg || 0) / maxIndeg.value
  return 9 + (0.6 * cites + 0.4 * central) * 25  // ~9–34px
}

// ------------------------------ elements --------------------------------- //
function elements(data: GraphData) {
  const nodeIds = new Set(data.nodes.map((n) => n.id))
  const useParents = layoutMode.value === 'dimensions' && hasClusters.value
  const parentIds = new Set((data.clusters ?? []).map((d) => d.id))
  const out: any[] = []

  if (useParents) {
    for (const d of data.clusters ?? []) {
      out.push({ data: { id: `dim:${d.id}`, isDim: 1, label: d.label, dcolor: d.color || '#5b86d6' } })
    }
  }
  for (const n of data.nodes) {
    const seed = n.level === 0 ? 1 : 0
    const cluster = n.cluster ?? ''
    const parent = useParents && !seed && parentIds.has(cluster) ? `dim:${cluster}` : undefined
    out.push({
      data: {
        id: n.id,
        label: n.title.length > 44 ? n.title.slice(0, 42) + '…' : n.title,
        full: n.title,
        level: n.level,
        cites: n.citation_count ?? 0,
        indeg: n.in_degree ?? 0,
        year: n.year ?? 0,
        imp: n.importance ?? 0.3,
        cluster,
        tv: n.top_venue ? 1 : 0,
        found: foundationalIds.value.has(n.id) ? 1 : 0,
        seed,
        ...(parent ? { parent } : {}),
      },
    })
  }
  for (let i = 0; i < data.edges.length; i++) {
    const e = data.edges[i]
    if (nodeIds.has(e.src) && nodeIds.has(e.dst)) {
      out.push({ data: { id: `e${i}`, source: e.src, target: e.dst, dir: e.direction } })
    }
  }
  return out
}

function layoutOpts() {
  if (layoutMode.value === 'levels') {
    return {
      name: 'concentric',
      concentric: (n: any) => 100 - n.data('level') * 20,
      levelWidth: () => 1, minNodeSpacing: 24, padding: 24, animate: false,
    }
  }
  // 'dimensions' and 'force' both use fcose (compound-aware, far cleaner than cose)
  return {
    name: 'fcose', quality: 'proof', animate: false, randomize: true,
    nodeDimensionsIncludeLabels: true, padding: 30,
    nodeSeparation: 80, idealEdgeLength: 80, nodeRepulsion: 7000,
    gravity: 0.3, gravityCompound: 1.2, packComponents: true,
  }
}

function buildStyle(): any[] {
  return [
    {
      selector: 'node',
      style: {
        'background-color': (n: any) => nodeColor(n.data()),
        width: (n: any) => nodeSize(n.data()),
        height: (n: any) => nodeSize(n.data()),
        label: 'data(label)',
        color: '#cfd9e6', 'font-size': 6.5, 'min-zoomed-font-size': 8,
        'text-wrap': 'wrap', 'text-max-width': '78px', 'text-valign': 'bottom', 'text-margin-y': 2,
        'text-outline-width': 2, 'text-outline-color': '#0e1116',
        // priority: seed (pink) > foundational (gold double-ring) > top venue (thin gold)
        'border-width': (n: any) => (n.data('seed') ? 2.5 : n.data('found') ? 3 : n.data('tv') ? 1.5 : 0),
        'border-color': (n: any) => (n.data('seed') ? '#ffd4dc' : n.data('found') ? '#ffcf6b' : '#ffd479'),
        'border-style': (n: any) => (n.data('found') && !n.data('seed') ? 'double' : 'solid'),
        'transition-property': 'opacity, border-width', 'transition-duration': 150,
      },
    },
    {
      selector: 'node:parent',  // dimension container boxes
      style: {
        'background-color': 'data(dcolor)', 'background-opacity': 0.05,
        'border-width': 1, 'border-color': 'data(dcolor)', 'border-opacity': 0.5,
        shape: 'round-rectangle', padding: 16,
        label: 'data(label)', color: 'data(dcolor)', 'font-size': 11, 'font-weight': 700,
        'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -4,
        'text-outline-width': 3, 'text-outline-color': '#0e1116', 'min-zoomed-font-size': 0,
      },
    },
    {
      selector: 'edge',
      style: {
        width: 1.1,
        'line-color': (e: any) => (e.data('dir') === 'reference' ? '#f0a868' : '#5ec8a6'),
        'target-arrow-color': (e: any) => (e.data('dir') === 'reference' ? '#f0a868' : '#5ec8a6'),
        'target-arrow-shape': 'triangle', 'arrow-scale': 0.6, 'curve-style': 'bezier', opacity: 0.18,
      },
    },
    { selector: 'edge.lit', style: { opacity: 0.85, width: 1.6 } },
    { selector: '.faded', style: { opacity: 0.06, 'text-opacity': 0.04 } },
    { selector: 'node.highlight', style: { 'border-width': 3, 'border-color': '#6ea8fe' } },
    { selector: 'node.nolabels', style: { label: '' } },
  ]
}

async function render() {
  if (!import.meta.client || !el.value) return
  const cytoscape = (await import('cytoscape')).default
  const fcose = (await import('cytoscape-fcose')).default
  try { cytoscape.use(fcose) } catch { /* already registered */ }
  if (cy) cy.destroy()
  cy = cytoscape({
    container: el.value,
    elements: elements(props.data),
    minZoom: 0.15, maxZoom: 3,
    style: buildStyle(),
    layout: layoutOpts(),
    wheelSensitivity: 0.6,
  })
  if (!showLabels.value) cy.nodes().addClass('nolabels')

  cy.on('tap', 'node', (evt: any) => {
    const n = evt.target
    if (n.data('isDim')) {                    // tapping a dimension box focuses it
      focusDim.value = focusDim.value === dimIdOf(n) ? null : dimIdOf(n)
      return
    }
    const id = n.id()
    emit('select', id === props.selectedId ? null : id)  // re-tap toggles off
  })
  cy.on('tap', (evt: any) => { if (evt.target === cy) emit('select', null) })
  cy.on('mouseover', 'node', (evt: any) => {
    const n = evt.target
    if (n.data('isDim')) return
    const p = evt.renderedPosition || n.renderedPosition()
    tip.value = { show: true, x: p.x, y: p.y, text: n.data('full') }
    emit('hover', n.id())
    if (!props.selectedId) hoverHighlight(n)
  })
  cy.on('mouseout', 'node', () => { tip.value.show = false; emit('hover', null); refreshEmphasis() })
  cy.on('pan zoom', () => { tip.value.show = false })
  refreshEmphasis()
}

const dimIdOf = (n: any) => String(n.id()).replace(/^dim:/, '')

// --------------------------- emphasis / fading --------------------------- //
function litNeighborhood(node: any) {
  const hood = node.closedNeighborhood()
  cy.elements().addClass('faded')
  hood.removeClass('faded')
  hood.edges().addClass('lit')
}
function hoverHighlight(node: any) {
  cy.elements().removeClass('faded').removeClass('lit')
  litNeighborhood(node)
}
/** Reconcile fading from the parent's selection + the active dimension filter. */
function refreshEmphasis() {
  if (!cy) return
  cy.elements().removeClass('faded').removeClass('lit')
  cy.nodes().removeClass('highlight')
  const sel = props.selectedId ? cy.getElementById(props.selectedId) : null
  if (sel && sel.length && !sel.data('isDim')) {
    litNeighborhood(sel)
    sel.addClass('highlight')
    return
  }
  if (focusDim.value) {
    cy.nodes().forEach((n: any) => {
      if (n.data('isDim')) return
      if (!(n.data('cluster') === focusDim.value || n.data('seed'))) n.addClass('faded')
    })
    cy.edges().forEach((e: any) => {
      if (e.source().hasClass('faded') || e.target().hasClass('faded')) e.addClass('faded')
    })
  }
}

// ------------------------------- controls -------------------------------- //
function fit() { cy && cy.fit(undefined, 30) }
function setLayout(m: LayoutMode) { userPickedLayout = true; layoutMode.value = m }
function setColor(m: ColorMode) { userPickedColor = true; colorMode.value = m }
function toggleFocus(id: string) { focusDim.value = focusDim.value === id ? null : id }
function zoomBy(f: number) {
  if (!cy) return
  const level = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * f))
  cy.animate({ zoom: { level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } }, { duration: 120 })
}
function zoomToSelected() {
  if (!cy) return
  const sel = cy.$('node.highlight')
  if (sel.length) cy.animate({ fit: { eles: sel.closedNeighborhood(), padding: 80 } }, { duration: 200 })
}

const legend = computed(() =>
  (props.data.clusters ?? []).map((d: Dimension) => ({ ...d, count: d.paper_ids.length })),
)

function applyStyle() { if (cy) cy.style(buildStyle()) }

watch(() => props.selectedId, () => refreshEmphasis())
watch(() => props.hoveredId, (id) => {
  if (!cy || props.selectedId) return
  const n = id ? cy.getElementById(id) : null
  if (n && n.length && !n.data('isDim')) hoverHighlight(n)
  else refreshEmphasis()
})
watch(focusDim, () => refreshEmphasis())
watch(layoutMode, () => render())
watch(colorMode, applyStyle)
watch(showLabels, () => {
  if (!cy) return
  cy.nodes().forEach((n: any) => n.toggleClass('nolabels', !showLabels.value && !n.data('isDim')))
})
watch(() => props.data, () => {
  // Auto-prefer the dimensional view once the AI grouping arrives (unless the user chose otherwise).
  if (!userPickedLayout) layoutMode.value = hasClusters.value ? 'dimensions' : 'levels'
  if (!userPickedColor) colorMode.value = hasClusters.value ? 'dimension' : 'importance'
  render()
}, { deep: true })
onMounted(() => {
  if (!userPickedLayout) layoutMode.value = hasClusters.value ? 'dimensions' : 'levels'
  if (!userPickedColor) colorMode.value = hasClusters.value ? 'dimension' : 'importance'
  render()
})
onBeforeUnmount(() => cy && cy.destroy())
</script>

<template>
  <div class="graph-wrap">
    <div class="graph-toolbar">
      <div class="seg">
        <button :class="{ active: layoutMode === 'dimensions' }" :disabled="!hasClusters"
          title="Group papers by AI dimension" @click="setLayout('dimensions')">Dimensions</button>
        <button :class="{ active: layoutMode === 'force' }" @click="setLayout('force')">Force</button>
        <button :class="{ active: layoutMode === 'levels' }" @click="setLayout('levels')">Rings</button>
      </div>
      <div class="seg" title="Colour nodes by">
        <button v-if="hasClusters" :class="{ active: colorMode === 'dimension' }" @click="setColor('dimension')">Dim</button>
        <button :class="{ active: colorMode === 'importance' }" @click="setColor('importance')">Impact</button>
        <button :class="{ active: colorMode === 'year' }" @click="setColor('year')">Year</button>
      </div>
      <div class="seg">
        <button @click="zoomBy(0.8)" title="Zoom out">−</button>
        <button @click="zoomBy(1.25)" title="Zoom in">+</button>
      </div>
      <button class="ghost" @click="fit">Fit</button>
      <button class="ghost" @click="zoomToSelected" title="Zoom to selected">Focus</button>
      <label class="lbl-toggle"><input type="checkbox" v-model="showLabels" /> labels</label>
    </div>

    <div ref="el" id="cy" />
    <div v-if="tip.show" class="cy-tip" :style="{ left: tip.x + 14 + 'px', top: tip.y + 12 + 'px' }">{{ tip.text }}</div>

    <!-- dimension legend doubles as a filter -->
    <div v-if="legend.length" class="dim-legend">
      <button class="dim-chip" :class="{ off: focusDim !== null }" @click="focusDim = null"
        title="Show all dimensions">
        <i class="sw" style="background:#f7768e" /> All <span class="ct">{{ data.nodes.length }}</span>
      </button>
      <button v-for="d in legend" :key="d.id" class="dim-chip"
        :class="{ active: focusDim === d.id, off: focusDim !== null && focusDim !== d.id }"
        :title="d.description" @click="toggleFocus(d.id)">
        <i class="sw" :style="{ background: d.color }" /> {{ d.label }} <span class="ct">{{ d.count }}</span>
      </button>
    </div>

    <div class="legend">
      <span><i class="dot" style="background:#f7768e" />seed (origin)</span>
      <span><i class="dot found-dot" />foundational (read first)</span>
      <span><i class="dot" style="background:#5b86d6" />size = impact + in-map links</span>
      <span><i style="background:#f0a868" />references (this cites →)</span>
      <span><i style="background:#5ec8a6" />citations (→ cites this)</span>
      <span class="muted">hover to preview · click to pin · click a dimension to filter</span>
    </div>
  </div>
</template>

<style scoped>
.dim-legend { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 2px 4px; }
.dim-chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; cursor: pointer;
  background: var(--bg-2); border: 1px solid var(--border); border-radius: 999px;
  color: var(--text); font-size: 12px; transition: border-color .12s, opacity .12s;
}
.dim-chip:hover { border-color: var(--accent); }
.dim-chip.active { border-color: var(--text); background: var(--bg-3); }
.dim-chip.off { opacity: 0.45; }
.dim-chip .sw { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.dim-chip .ct { color: var(--text-dim); font-variant-numeric: tabular-nums; }
.legend i.found-dot { background: transparent; border: 2px double #ffcf6b; box-sizing: border-box; }
</style>
