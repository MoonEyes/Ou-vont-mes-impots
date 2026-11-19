import { readFileSync } from 'node:fs'
import { defineConfig } from 'vitest/config'

// Adresse publique du site : une seule source, adresse-site.json (OVMI_URL_SITE la remplace le temps d'un build).
// Reprise par le prérendu (scripts/prerendre.mjs), par index.html (%OVMI_URL_SITE%, %OVMI_ADRESSE_SITE%) et par le
// code (__URL_SITE__, __ADRESSE_SITE__ : signalement, carte de partage). Voir docs/SEO.md.
const URL_SITE = (process.env.OVMI_URL_SITE || (JSON.parse(readFileSync(new URL('./adresse-site.json', import.meta.url), 'utf8')).url as string)).replace(/\/*$/, '/')
const ADRESSE_SITE = URL_SITE.replace(/^https?:\/\//, '').replace(/\/$/, '')

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
    __URL_SITE__: JSON.stringify(URL_SITE),
    __ADRESSE_SITE__: JSON.stringify(ADRESSE_SITE),
  },
  plugins: [
    {
      name: 'ovmi-adresse-site',
      transformIndexHtml: { order: 'pre', handler: (html: string) => html.replaceAll('%OVMI_URL_SITE%', URL_SITE).replaceAll('%OVMI_ADRESSE_SITE%', ADRESSE_SITE) },
    },
  ],
  // Worker du calcul (src/calcul/travailleur.ts) en module ES, comme le reste du site.
  worker: { format: 'es' },
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
