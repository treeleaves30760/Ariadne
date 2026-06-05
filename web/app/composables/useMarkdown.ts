import MarkdownIt from 'markdown-it'

// html:false keeps model-generated text from injecting raw HTML; linkify makes URLs clickable.
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

export function useMarkdown() {
  return { render: (text: string | null | undefined) => (text ? md.render(text) : '') }
}
