import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const GITHUB_REPO = 'https://github.com/treeleaves30760/Ariadne';

const config: Config = {
  title: 'Ariadne',
  tagline: 'AI-built citation maps so you never miss a key paper',
  favicon: 'img/logo.svg',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Production URL and base path (GitHub Pages project site).
  url: 'https://treeleaves30760.github.io',
  baseUrl: '/Ariadne/',

  // GitHub Pages deployment config.
  organizationName: 'treeleaves30760',
  projectName: 'Ariadne',
  trailingSlash: false,

  onBrokenLinks: 'throw',

  // Parse `.md` as CommonMark and `.mdx` as MDX, so plain Markdown docs are robust.
  markdown: {
    format: 'detect',
  },

  // English (default) + 繁體中文.
  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'zh-Hant'],
    localeConfigs: {
      en: {label: 'English'},
      'zh-Hant': {label: '繁體中文', htmlLang: 'zh-Hant'},
    },
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: `${GITHUB_REPO}/tree/main/docs/`,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Ariadne',
      logo: {
        alt: 'Ariadne',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          type: 'localeDropdown',
          position: 'right',
        },
        {
          href: GITHUB_REPO,
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'Overview', to: '/docs/'},
            {label: 'Usage guide', to: '/docs/usage'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: GITHUB_REPO},
            {label: 'Issues', href: `${GITHUB_REPO}/issues`},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Ariadne. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
