// Construction du site pour les tests qui lisent dist/ (bundle, prérendu) : sur un clone propre, rien n'existe
// encore. On copie les données (site/data vers public/data), on construit puis on prérend, une seule fois même
// si plusieurs fichiers de test le demandent en parallèle (verrou par dossier, création atomique).
import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, rmSync, statSync } from 'node:fs'
import { join } from 'node:path'

const RACINE = process.cwd()
const DIST = join(RACINE, 'dist')
const VERROU = join(RACINE, 'node_modules', '.verrou-construction')
const PERIME_MS = 20 * 60 * 1000

const pret = () => existsSync(join(DIST, 'prerendu.json')) && existsSync(join(DIST, 'data', '_manifeste.json'))
const attendre = (ms: number) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)

function prendreVerrou(): boolean {
  try {
    mkdirSync(VERROU)
    return true
  } catch {
    // Verrou laissé par une exécution interrompue : on le reprend.
    if (existsSync(VERROU) && Date.now() - statSync(VERROU).mtimeMs > PERIME_MS) {
      rmSync(VERROU, { recursive: true, force: true })
      return prendreVerrou()
    }
    return false
  }
}

/** Garantit dist/ complet (pages prérendues et données) ; ne refait rien si « npm run build » est déjà passé. */
export function assurerSite(): void {
  while (!pret()) {
    if (!prendreVerrou()) {
      attendre(1000)
      continue
    }
    try {
      if (pret()) return
      if (!existsSync(join(RACINE, 'public', 'data', '_manifeste.json'))) execSync('node scripts/copier-donnees.mjs', { cwd: RACINE, stdio: 'ignore' })
      execSync('npx vite build', { cwd: RACINE, stdio: 'ignore' })
      execSync('node scripts/prerendre.mjs', { cwd: RACINE, stdio: 'ignore' })
    } finally {
      rmSync(VERROU, { recursive: true, force: true })
    }
  }
}
