import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Translate from '@docusaurus/Translate';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import HomepageFeatures from '@site/src/components/HomepageFeatures';

import styles from './index.module.css';

const GITHUB_REPO = 'https://github.com/treeleaves30760/Ariadne';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={styles.hero}>
      <div className={clsx('container', styles.heroInner)}>
        <Heading as="h1" className={styles.heroTitle}>
          {siteConfig.title}
        </Heading>
        <p className={styles.heroTagline}>
          <Translate id="homepage.tagline">
            AI-built citation maps so you never miss a key paper.
          </Translate>
        </p>
        <p className={styles.heroSubtitle}>
          <Translate id="homepage.subtitle">
            Start from one paper or benchmark, expand its citation graph in both
            directions, let the OpenAI Codex CLI filter every level for relevance,
            and explore the result as an interactive graph with progressive reports.
          </Translate>
        </p>
        <div className={styles.buttons}>
          <Link className="button button--primary button--lg" to="/docs/usage">
            <Translate id="homepage.cta.start">Get started →</Translate>
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/">
            <Translate id="homepage.cta.overview">Overview</Translate>
          </Link>
          <Link
            className={clsx('button button--outline button--lg', styles.ghButton)}
            href={GITHUB_REPO}>
            GitHub
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={siteConfig.title}
      description="AI-built citation maps so you never miss a key paper.">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );
}
