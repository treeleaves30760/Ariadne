export interface ExternalIds {
  doi?: string | null
  arxiv?: string | null
  s2?: string | null
  openalex?: string | null
}

export interface Candidate {
  id: string
  title: string
  year?: number | null
  authors: string[]
  venue?: string | null
  citation_count?: number | null
  source: string
  external_ids: ExternalIds
}

export interface JobProgress {
  status: string
  current_level: number
  nodes: number
  edges: number
  codex_calls: number
  message: string
  reports_available: string[]
}

export interface Job {
  id: string
  params: Record<string, unknown>
  progress: JobProgress
  created_at: string
  error?: string | null
  name?: string | null         // user-assigned label (overrides seed_title)
  seed_title?: string | null   // resolved seed paper title (default label)
}

export interface GraphNode {
  id: string
  title: string
  year?: number | null
  authors: string[]
  venue?: string | null
  citation_count?: number | null
  url?: string | null
  pdf_url?: string | null
  external_ids: ExternalIds
  level: number
  relevance?: number | null
  importance?: number | null
  top_venue?: boolean
  reason?: string
  summary?: string | null
}

export interface GraphEdge {
  src: string
  dst: string
  direction: 'reference' | 'citation'
  level: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface ReportCluster {
  theme: string
  summary: string
  paper_ids: string[]
}

export interface WebSource {
  title: string
  url: string
  note: string
}

export interface Report {
  level: string
  overview: string
  clusters: ReportCluster[]
  must_reads: string[]
  gaps: string[]
  sources?: WebSource[]
}

export interface QAResult {
  question: string
  answer: string
  citations: string[]
  confidence: number
  sources?: WebSource[]
  tools_used?: string[]
  created_at: string
}

export interface Settings {
  model: string | null
  reasoning_effort: string | null
  api_base: string | null
  api_key_set: boolean
  api_key_masked: string | null
  available_models: string[]
  reasoning_efforts: string[]
}
