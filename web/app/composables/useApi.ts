import type { Candidate, GraphData, Job, QAResult, Report } from '~/types'

export function useApi() {
  const base = useRuntimeConfig().public.apiBase as string

  async function req<T>(path: string, opts: any = {}): Promise<T> {
    return await $fetch<T>(`${base}${path}`, opts)
  }

  return {
    base,
    resolve: (query: string, limit = 10) =>
      req<{ candidates: Candidate[] }>('/resolve', { method: 'POST', body: { query, limit } }),

    createJob: (body: Record<string, unknown>) =>
      req<Job>('/jobs', { method: 'POST', body }),

    getJob: (id: string) => req<Job>(`/jobs/${id}`),

    listJobs: () => req<Job[]>('/jobs'),

    ask: (id: string, question: string) =>
      req<QAResult>(`/jobs/${id}/ask`, { method: 'POST', body: { question } }),

    getQa: (id: string) => req<QAResult[]>(`/jobs/${id}/qa`),

    getGraph: (id: string) => req<GraphData>(`/jobs/${id}/graph`),

    listReports: (id: string) => req<{ levels: string[] }>(`/jobs/${id}/reports`),

    getReport: (id: string, level: string) => req<Report>(`/jobs/${id}/reports/${level}`),

    exportUrl: (id: string, format: 'bibtex' | 'markdown') =>
      `${base}/jobs/${id}/export?format=${format}`,

    /** Subscribe to job progress via SSE. Returns an unsubscribe function. */
    streamEvents(id: string, onEvent: (type: string, data: any) => void): () => void {
      const es = new EventSource(`${base}/jobs/${id}/events`)
      const terminal = new Set(['done', 'failed', 'end'])
      const handler = (type: string) => (e: MessageEvent) => {
        try {
          onEvent(type, JSON.parse(e.data))
        } catch {
          onEvent(type, e.data)
        }
        // Close on terminal events so EventSource doesn't auto-reconnect in a loop.
        if (terminal.has(type)) es.close()
      }
      for (const t of ['snapshot', 'progress', 'note', 'reporting', 'report_ready', 'done', 'failed', 'end']) {
        es.addEventListener(t, handler(t))
      }
      es.onerror = () => { /* transient; server closes the stream on terminal event */ }
      return () => es.close()
    },
  }
}
