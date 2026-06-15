import type { Candidate, GraphData, Job, QAResult, Report, Settings } from '~/types'

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

    renameJob: (id: string, name: string) =>
      req<Job>(`/jobs/${id}`, { method: 'PATCH', body: { name } }),

    deleteJob: (id: string) =>
      req<{ ok: boolean }>(`/jobs/${id}`, { method: 'DELETE' }),

    ask: (id: string, question: string, useTools = true) =>
      req<QAResult>(`/jobs/${id}/ask`, { method: 'POST', body: { question, use_tools: useTools } }),

    getQa: (id: string) => req<QAResult[]>(`/jobs/${id}/qa`),

    getSettings: () => req<Settings>('/settings'),

    putSettings: (body: Record<string, unknown>) =>
      req<{ ok: boolean }>('/settings', { method: 'PUT', body }),

    getGraph: (id: string) => req<GraphData>(`/jobs/${id}/graph`),

    listReports: (id: string) => req<{ levels: string[] }>(`/jobs/${id}/reports`),

    getReport: (id: string, level: string) => req<Report>(`/jobs/${id}/reports/${level}`),

    exportUrl: (id: string, format: 'bibtex' | 'markdown') =>
      `${base}/jobs/${id}/export?format=${format}`,

    /** Subscribe to job progress via SSE. Returns an unsubscribe function.
     *  Besides the server's progress events, the caller also receives synthetic
     *  events so it can tell "still generating" from "truly disconnected":
     *    - 'heartbeat'    server is alive but quiet (e.g. a long Codex call)
     *    - 'reconnecting' transport dropped; EventSource is auto-retrying
     *    - 'stale'        connection closed for good / worker gone → poll getJob
     */
    streamEvents(id: string, onEvent: (type: string, data: any) => void): () => void {
      const es = new EventSource(`${base}/jobs/${id}/events`)
      const terminal = new Set(['done', 'failed', 'end', 'stale'])
      let closed = false
      const handler = (type: string) => (e: MessageEvent) => {
        try {
          onEvent(type, JSON.parse(e.data))
        } catch {
          onEvent(type, e.data)
        }
        // Close on terminal events so EventSource doesn't auto-reconnect in a loop.
        if (terminal.has(type)) { closed = true; es.close() }
      }
      for (const t of ['snapshot', 'progress', 'note', 'reporting', 'report_ready',
                       'clusters_ready', 'links_ready', 'heartbeat', 'done', 'failed', 'stale', 'end']) {
        es.addEventListener(t, handler(t))
      }
      es.onerror = () => {
        if (closed) return
        // readyState CLOSED (2): EventSource gave up (e.g. 404 / server gone) →
        //   stop and let the caller fall back to polling getJob.
        // readyState CONNECTING (0): transient drop, it's auto-retrying → just a hint.
        if (es.readyState === EventSource.CLOSED) {
          closed = true
          onEvent('stale', { reason: 'connection closed' })
        } else {
          onEvent('reconnecting', { readyState: es.readyState })
        }
      }
      return () => { closed = true; es.close() }
    },
  }
}
