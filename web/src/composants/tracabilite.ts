// Taux de traçabilité par bloc (site/data/tracabilite/, produit par une autre étape du pipeline).
// Affiché seulement si le dossier existe et porte sur le même millésime que l'écran.
import { charger, manifeste } from '../donnees'
import { h, pct } from '../util'

interface Part {
  libelle: string
  eur: number
  pct: number
  statut: string
  ecart_millesime_ans?: number
}
interface EntreeTrac {
  id: string
  taux_tracabilite_pct?: number
  parts?: Record<string, Part>
  approche?: boolean
  [k: string]: unknown
}
interface Resume {
  millesime: string
  parts: Record<string, string>
  methode?: string
  limites?: string[]
  global: EntreeTrac
  grands_postes?: EntreeTrac[]
  missions?: EntreeTrac[]
  programmes?: EntreeTrac[]
}

const ORDRE = ['beneficiaire_identifie', 'nominatif_par_choix', 'anonyme_par_nature', 'non_publie']
const CLASSES: Record<string, string> = {
  beneficiaire_identifie: 'c0',
  nominatif_par_choix: 'c2',
  anonyme_par_nature: 'c9',
  non_publie: 'c11',
}

async function resume(): Promise<Resume | null> {
  const m = await manifeste()
  if (!m.optionnels.tracabilite?.includes('tracabilite/resume.json')) return null
  try {
    return await charger<Resume>('tracabilite/resume.json')
  } catch {
    return null
  }
}

/** niveau : racine | grand_poste | mission | programme ; id : identifiant de l'arbre ou numéro de programme. */
export async function blocTracabilite(niveau: string, id: string, millesime: string): Promise<string> {
  const r = await resume()
  if (!r || r.millesime !== millesime) return ''
  let e: EntreeTrac | undefined
  if (niveau === 'racine') e = r.global
  else if (niveau === 'grand_poste') e = r.grands_postes?.find((x) => x.id === id)
  else if (niveau === 'mission') e = r.missions?.find((x) => x.id === id)
  else if (niveau === 'programme') {
    const num = /(\d{3})$/.exec(id)?.[1] ?? id
    const p = r.programmes?.find((x) => x.id === num)
    if (p && typeof p.fichier === 'string') {
      try {
        e = await charger<EntreeTrac>(p.fichier)
      } catch {
        e = p
      }
    } else e = p
  }
  if (!e || typeof e.taux_tracabilite_pct !== 'number') return ''
  const parts = e.parts
    ? ORDRE.filter((k) => e!.parts![k]).map((k) => ({ cle: k, ...e!.parts![k] }))
    : ORDRE.map((k) => ({ cle: k, libelle: r.parts[k], pct: Number(e![`${k}_pct`] ?? 0), statut: '', eur: 0, ecart_millesime_ans: 0 }))
  const approche = parts.some((p) => p.statut === 'approche') || e.approche
  return `<details class="carte">
  <summary>Traçabilité de ce bloc : ${h(pct(e.taux_tracabilite_pct))}${approche ? ' (approché)' : ''}</summary>
  <p>Part de l’argent dont on sait à qui il va : bénéficiaire nommé, catégorie d’agents publiée ou porteurs de la dette.</p>
  <div class="empile" aria-hidden="true">${parts.map((p) => `<span class="${CLASSES[p.cle]}" data-l="${Math.max(0, p.pct).toFixed(3)}"></span>`).join('')}</div>
  <ul>${parts
    .map(
      (p) =>
        `<li><span class="pastille ${CLASSES[p.cle]}" aria-hidden="true"></span>${h(p.libelle)} : ${h(pct(p.pct))}${
          p.statut === 'approche' ? ` (approché${p.ecart_millesime_ans ? `, données décalées de ${p.ecart_millesime_ans} an` : ''})` : ''
        }</li>`,
    )
    .join('')}</ul>
  ${r.limites?.length ? `<p class="aide">Limites : ${r.limites.map(h).join(' ')}</p>` : ''}
  <p class="source">site/data/tracabilite (${h(r.millesime)})</p>
</details>`
}
