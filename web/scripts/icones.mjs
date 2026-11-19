// Icônes PNG du manifeste (public/icone-192.png, icone-512.png, icone-masquable-512.png), tirées du logo unique
// public/favicon.svg (même tracé que le symbole #logo-billet de index.html), en version claire.
// À relancer à la main après un changement du logo : node scripts/icones.mjs (navigateur sans interface requis :
// Chrome ou Chromium, chemin forçable par OVMI_CHROME). Aucune dépendance ajoutée.
import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..')
const favicon = readFileSync(join(WEB, 'public', 'favicon.svg'), 'utf8')
// Version masquable : fond plein sur toute l'image, logo dans la zone sûre (cercle central de 80 %).
const masquable = favicon.replace('viewBox="-2 -9 50 50"', 'viewBox="-14 -21 74 74"').replace('<rect class="f" x="-2" y="-9" width="50" height="50" rx="11"/>', '<rect class="f" x="-14" y="-21" width="74" height="74"/>')
const navigateurs = [process.env.OVMI_CHROME, 'google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'].filter(Boolean)

function capturer(svg, taille, sortie) {
  const tmp = mkdtempSync(join(tmpdir(), 'ovmi-icone-'))
  try {
    const page = join(tmp, 'icone.html')
    writeFileSync(page, `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:transparent}svg{display:block;width:${taille}px;height:${taille}px}</style></head><body>${svg}</body></html>`)
    for (const n of navigateurs) {
      const capture = join(tmp, 'icone.png')
      const r = spawnSync(n, ['--headless', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--force-device-scale-factor=1', '--default-background-color=00000000', `--user-data-dir=${join(tmp, 'profil')}`, `--window-size=${taille},${taille}`, `--screenshot=${capture}`, pathToFileURL(page).href], { stdio: 'ignore', timeout: 60000 })
      if (r.error?.code === 'ENOENT') continue
      const png = readFileSync(capture)
      if (r.status !== 0 || png.readUInt32BE(16) !== taille || png.readUInt32BE(20) !== taille) throw new Error(`capture ratée : ${sortie}`)
      copyFileSync(capture, join(WEB, 'public', sortie))
      return
    }
    throw new Error('aucun navigateur sans interface (Chrome ou Chromium) trouvé')
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
}

capturer(favicon, 192, 'icone-192.png')
capturer(favicon, 512, 'icone-512.png')
capturer(masquable, 512, 'icone-masquable-512.png')
console.log('Icônes régénérées depuis public/favicon.svg : icone-192.png, icone-512.png, icone-masquable-512.png')
