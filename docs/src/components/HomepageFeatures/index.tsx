import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import Translate from '@docusaurus/Translate';
import styles from './styles.module.css';

type FeatureItem = {
  icon: ReactNode;
  title: ReactNode;
  description: ReactNode;
};

const svgProps = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
};

const FeatureList: FeatureItem[] = [
  {
    icon: (
      <svg {...svgProps}>
        <circle cx="12" cy="5" r="2" />
        <circle cx="5" cy="18" r="2" />
        <circle cx="19" cy="18" r="2" />
        <path d="M11 6.3 6.2 16M13 6.3 17.8 16M7 18h10" />
      </svg>
    ),
    title: <Translate id="feature.graph.title">Bidirectional citation graph</Translate>,
    description: (
      <Translate id="feature.graph.desc">
        Expand references (backward) and citations (forward) to depth 3–5 from a
        single seed paper or benchmark.
      </Translate>
    ),
  },
  {
    icon: (
      <svg {...svgProps}>
        <path d="M4 5h16l-6.2 7v5.2l-3.6-1.8V12z" />
      </svg>
    ),
    title: <Translate id="feature.ai.title">AI relevance filtering</Translate>,
    description: (
      <Translate id="feature.ai.desc">
        The OpenAI Codex CLI scores every level for relevance and writes short
        explanations, keeping only the papers that matter.
      </Translate>
    ),
  },
  {
    icon: (
      <svg {...svgProps}>
        <path d="M7 3h7l4 4v14H7z" />
        <path d="M14 3v4h4" />
        <path d="M10 13h5M10 16.5h5" />
      </svg>
    ),
    title: <Translate id="feature.reports.title">Progressive reports</Translate>,
    description: (
      <Translate id="feature.reports.desc">
        Reports at depth 3, 4, and 5, a final synthesis, plus a DuckDuckGo
        web-context report that surfaces surveys and recent work.
      </Translate>
    ),
  },
  {
    icon: (
      <svg {...svgProps}>
        <path d="M5 5h14v10H10l-4 3v-3H5z" />
        <path d="M9 9h6M9 12h4" />
      </svg>
    ),
    title: <Translate id="feature.ask.title">Ask the literature</Translate>,
    description: (
      <Translate id="feature.ask.desc">
        A tool-augmented chatbot answers grounded in your corpus with clickable
        citations, optionally verified with web search and open-access PDFs.
      </Translate>
    ),
  },
  {
    icon: (
      <svg {...svgProps}>
        <path d="M5 20v-6M12 20V5M19 20v-9" strokeWidth={2} />
      </svg>
    ),
    title: <Translate id="feature.rank.title">Importance ranking</Translate>,
    description: (
      <Translate id="feature.rank.desc">
        Rank papers by an importance score (relevance × citations × top-venue) in
        a sortable table, with top venues marked.
      </Translate>
    ),
  },
  {
    icon: (
      <svg {...svgProps}>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M15.5 8.5 11 11l-2.5 4.5L13 13z" />
      </svg>
    ),
    title: <Translate id="feature.explore.title">Explore &amp; export</Translate>,
    description: (
      <Translate id="feature.explore.desc">
        A readable Cytoscape graph with per-paper AI summaries and a live activity
        feed; export your reading list as BibTeX or Markdown.
      </Translate>
    ),
  },
];

function Feature({icon, title, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4', styles.featureCol)}>
      <div className={styles.card}>
        <div className={styles.icon}>{icon}</div>
        <Heading as="h3" className={styles.cardTitle}>
          {title}
        </Heading>
        <p className={styles.cardDesc}>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
