import { readFileSync } from 'node:fs'
import { defineConfig } from 'vitest/config'

const version = (paquet: string) =>
  JSON.parse(readFileSync(new URL(`./node_modules/${paquet}/package.json`, import.meta.url), 'utf8')).version as string

// base relative : le site fonctionne à la racine d'un domaine comme sous
// /Ou-vont-mes-impots/ (GitHub Pages), sans réécriture d'URL.
export default defineConfig({
  base: './',
  define: {
    __VERSION_MODELE_SOCIAL__: JSON.stringify(version('modele-social')),
    __VERSION_PUBLICODES__: JSON.stringify(version('publicodes')),
    __VERSION_ECHARTS__: JSON.stringify(version('echarts')),
  },
  build: {
    target: 'es2020',
    sourcemap: false,
    assetsInlineLimit: 0,
    // Pas de polyfill modulepreload (il ferait des fetch) : les navigateurs visés le gèrent nativement.
    modulePreload: { polyfill: false },
    chunkSizeWarningLimit: 1200,
  },
  test: {
    include: ['tests/**/*.test.ts'],
    testTimeout: 120000,
    hookTimeout: 300000,
  },
})
