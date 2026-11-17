// Copie site/data vers web/public/data (jamais committée, voir .gitignore) et écrit
// public/data/_manifeste.json : présence des dossiers optionnels produits par d'autres
// étapes du pipeline (prelevements/, tracabilite/, affectation_prelevements.json).
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync, readFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ici = dirname(fileURLToPath(import.meta.url))
const source = process.env.OVMI_DONNEES ?? join(ici, '..', '..', 'site', 'data')
const cible = join(ici, '..', 'public', 'data')

if (!existsSync(source)) {
  console.error(`Données introuvables : ${source}`)
  process.exit(1)
}
rmSync(cible, { recursive: true, force: true })
mkdirSync(cible, { recursive: true })
// Les CSV (tables Frictionless) ne sont pas lus par le site.
cpSync(source, cible, { recursive: true, filter: (f) => !f.endsWith('.csv') })

function lister(dossier) {
  const d = join(cible, dossier)
  if (!existsSync(d) || !statSync(d).isDirectory()) return null
  const out = []
  const parcourir = (x) => {
    for (const n of readdirSync(x)) {
      const p = join(x, n)
      if (statSync(p).isDirectory()) parcourir(p)
      else if (n.endsWith('.json')) out.push(relative(cible, p).split('\\').join('/'))
    }
  }
  parcourir(d)
  return out.sort()
}

let versionContrat = null
try {
  versionContrat = JSON.parse(readFileSync(join(cible, 'meta.json'), 'utf8')).version_contrat ?? null
} catch {}

const manifeste = {
  genere_le: new Date().toISOString(),
  version_contrat: versionContrat,
  optionnels: {
    prelevements: lister('prelevements'),
    tracabilite: lister('tracabilite'),
    affectation_prelevements: existsSync(join(cible, 'affectation_prelevements.json')),
  },
}
writeFileSync(join(cible, '_manifeste.json'), JSON.stringify(manifeste))

// Nombre de sources publiques collectées (collecte/catalogue.json, hors sources non collectables),
// pour les pages Accueil et Démarche : jamais codé en dur dans le site.
const catalogue = join(ici, '..', '..', 'collecte', 'catalogue.json')
if (existsSync(catalogue)) {
  try {
    const c = JSON.parse(readFileSync(catalogue, 'utf8'))
    const sources = Array.isArray(c.sources) ? c.sources : []
    const domaines = {}
    for (const x of sources) domaines[x.domaine ?? 'autre'] = (domaines[x.domaine ?? 'autre'] ?? 0) + 1
    writeFileSync(
      join(cible, '_sources.json'),
      JSON.stringify({
        source: 'collecte/catalogue.json',
        genere_le: manifeste.genere_le,
        sources_collectees: sources.length,
        non_collectables: Array.isArray(c.non_collectables) ? c.non_collectables.length : 0,
        domaines,
      }),
    )
  } catch {
    /* catalogue illisible : le site affiche le texte sans nombre */
  }
}
let n = 0
const compter = (x) => readdirSync(x).forEach((f) => (statSync(join(x, f)).isDirectory() ? compter(join(x, f)) : n++))
compter(cible)
console.log(`Données copiées : ${n} fichiers vers ${relative(process.cwd(), cible)}`)
