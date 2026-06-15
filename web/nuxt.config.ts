import os from 'node:os'

// macOS workaround: Nuxt's vite-node dev IPC uses a Unix domain socket created
// under os.tmpdir(). macOS's default $TMPDIR (/var/folders/.../T/) is ~48 bytes,
// which pushes the socket path past the 104-byte sun_path limit, so connect()
// fails with EINVAL and every dev request 500s. The fixed socket suffix is
// ~63 bytes, leaving ~40 for $TMPDIR; point it at a short path when it's too long.
// See node_modules/@nuxt/vite-builder/dist/index.mjs → pickSocketPath().
if (process.platform === 'darwin' && (process.env.TMPDIR ?? os.tmpdir()).length > 40) {
  process.env.TMPDIR = '/tmp'
}

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8008',
    },
  },
  app: {
    head: {
      title: 'Ariadne — AI-built citation maps',
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
    },
  },
  css: ['~/assets/main.css'],
})
