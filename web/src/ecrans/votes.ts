// Votes, amendements et mouvements de crédits (site/data/decisions/).
import { listeProgrammes, chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, eurLisible, h, source } from '../util'
import { enCours } from './dette'

interface Annee {
  amendements?: { deposes_an: number; deposes_senat: number; adoptes_seance_an: number; adoptes_seance_senat: number; adoptes_commission_an: number; net_cp_adopte_seance: number }
  amendements_adoptes?: { chambre: string; texte: string; lieu: string; numero: string; date: string; auteur: { type: string; nom: string | null; groupe: string | null }; cp: number; url: string }[]
}
interface Programme {
  source: string
  millesime: string
  programme: string
  libelle: string
  annees: Record<string, Annee>
  chronologie: { date: string; etape: string; cp: number; url: string }[]
}
interface Index {
  source: string
  millesime: string
  comptes: { amendements_credits_an: number; amendements_credits_senat: number; adoptes_seance_an: number; adoptes_seance_senat: number; scrutins: number; mouvements: { textes: number; lignes: number } }
  regle_personnes: string
}
interface Scrutins {
  source: string
  scrutins: { numero: number; date: string; texte: string; type: string; objet: string; resultat: string; pour: number; contre: number; abstentions: number; url: string }[]
}

export const REGLE_AMENDEMENTS = 'Ordre : date d’adoption, du plus récent au plus ancien (les 12 derniers), quel que soit le groupe de l’auteur.'

const signe = (x: number) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${eurLisible(Math.abs(x))}`

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const p = params.get('p')
  const progs = (await listeProgrammes()).sort((a, b) => Number(a.numero) - Number(b.numero))
  const choix = `<label for="prog-votes">Programme</label><select id="prog-votes"><option value="">Tous les programmes</option>${progs
    .map((x) => `<option value="${x.numero}"${x.numero === p ? ' selected' : ''}>${h(x.numero)} ${h(x.nom)}</option>`)
    .join('')}</select>`
  const idx = await chargerSiPresent<Index>('decisions/index.json')
  if (!idx) {
    cible.innerHTML = enCours('Votes, amendements et mouvements de crédits', 'Amendements, scrutins et mouvements de crédits publiés au Journal officiel.')
    return
  }
  let corps = ''
  if (p && /^\d{3}$/.test(p)) {
    const d = await chargerSiPresent<Programme>(`decisions/programme_${p}.json`)
    if (!d) corps = absent(`Pas de décisions publiées pour le programme ${p}.`)
    else {
      const annees = Object.keys(d.annees).sort().reverse()
      const adoptes = annees
        .flatMap((a) => d.annees[a].amendements_adoptes ?? [])
        .sort((a, b) => b.date.localeCompare(a.date) || a.numero.localeCompare(b.numero, 'fr', { numeric: true }))
        .slice(0, 12)
      corps = `<h2>Programme ${h(d.programme)} : ${h(d.libelle)}</h2>
<div class="tableau-defile"><table><caption>Amendements de crédits (Assemblée et Sénat)</caption><thead><tr><th scope="col">Loi de finances</th><th scope="col" class="nombre">Déposés</th><th scope="col" class="nombre">Adoptés en séance</th><th scope="col" class="nombre">Effet net adopté en séance</th></tr></thead><tbody>${annees
        .filter((a) => d.annees[a].amendements)
        .map((a) => {
          const x = d.annees[a].amendements!
          return `<tr><th scope="row">${a}</th><td class="nombre">${x.deposes_an + x.deposes_senat}</td><td class="nombre">${x.adoptes_seance_an + x.adoptes_seance_senat}</td><td class="nombre">${h(signe(x.net_cp_adopte_seance))}</td></tr>`
        })
        .join('')}</tbody></table></div>
${
  adoptes.length
    ? `<h3>Derniers amendements adoptés</h3><p class="aide" data-regle-ordre>${h(REGLE_AMENDEMENTS)}</p><ul class="lignes">${adoptes
        .map(
          (a) =>
            `<li><span><a href="${h(a.url)}" rel="noopener noreferrer">${h(a.texte)}, amendement ${h(a.numero)}</a></span><span class="montant">${h(signe(a.cp))}</span><span class="dest">${h(a.date)} · ${h(a.lieu)} · ${h(a.auteur.nom ?? a.auteur.type)}${a.auteur.groupe ? ` (${h(a.auteur.groupe)})` : ''}</span></li>`,
        )
        .join('')}</ul>`
    : ''
}
<h3>Mouvements de crédits publiés au Journal officiel</h3>
<ul class="lignes">${d.chronologie
        .slice(-12)
        .reverse()
        .map((c) => `<li><span><a href="${h(c.url)}" rel="noopener noreferrer">${h(c.etape)}</a></span><span class="montant">${h(signe(c.cp))}</span><span class="dest">${h(c.date)}</span></li>`)
        .join('')}</ul>
${source(d.source, d.millesime)}
<ul class="liens-sortie">
  <li><a href="${lien('/beneficiaires/programme', { p })}">Le programme ${h(p)} en détail</a></li>
  <li><a href="${lien('/decisions/realisations', { p })}">Ce qui a été fait (programme ${h(p)})</a></li>
</ul>`
    }
  } else {
    const sc = await chargerSiPresent<Scrutins>('decisions/scrutins.json')
    const c = idx.comptes
    corps = `<div class="carte"><p>Pendant la 17e législature : ${h(String(c.amendements_credits_an + c.amendements_credits_senat))} amendements modifiant des crédits déposés, dont ${h(String(c.adoptes_seance_an + c.adoptes_seance_senat))} adoptés en séance ; ${h(String(c.scrutins))} scrutins publics sur les lois de finances ; ${h(String(c.mouvements.textes))} décrets et arrêtés de mouvements de crédits (${h(String(c.mouvements.lignes))} lignes).</p>${source(idx.source, idx.millesime)}</div>
${
  sc
    ? `<h2>Derniers votes d’ensemble sur les lois de finances</h2><ul class="lignes">${sc.scrutins
        .filter((s) => s.type === 'ensemble')
        .slice(-10)
        .reverse()
        .map((s) => `<li><span><a href="${h(s.url)}" rel="noopener noreferrer">${h(s.texte)} : ${h(s.objet)}</a></span><span class="montant">${h(s.resultat)}</span><span class="dest">${h(s.date)} · ${s.pour} pour, ${s.contre} contre, ${s.abstentions} abstentions</span></li>`)
        .join('')}</ul>${source(sc.source)}`
    : ''
}`
  }
  cible.innerHTML = `<h1>Votes, amendements et mouvements de crédits</h1>
<p class="chapeau">Le Parlement vote le budget ; le Gouvernement peut ensuite déplacer, annuler ou reporter des crédits par décret ou arrêté publié au Journal officiel.</p>
${choix}
${corps}
<p class="aide">${h(idx.regle_personnes)}</p>`
  cible.querySelector<HTMLSelectElement>('#prog-votes')?.addEventListener('change', (e) => {
    location.hash = lien('/decisions/votes', { p: (e.target as HTMLSelectElement).value })
  })
}
