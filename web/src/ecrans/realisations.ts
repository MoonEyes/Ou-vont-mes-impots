// Écran 7 : ce qui a été fait (prévu/dépensé par année, indicateurs avec tendance, Cour des comptes).
import { brancherFiltre, choixProgramme } from '../composants/choix-programme'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, barres, eurLisible, h, pct, source, sur100, surligne } from '../util'

interface Annee {
  annee: number
  source: string | null
  vote_lfi_eur: number | null
  depense_constatee_eur: number | null
  ecart_pct: number | null
  eur_sur_100?: number
  trou?: string
}
interface Valeur {
  annee: number
  valeur: number | null
  brut: string
  source: string
}
interface Indicateur {
  id: string
  objectif: string
  indicateur: string
  sous_indicateur: string
  unite: string
  indicateur_de_contexte: boolean | null
  valeurs: Valeur[]
  cibles: (Valeur & { note?: string })[]
  sens_souhaite: { valeur: string; justification: string }
  tendance: {
    valeur: string
    de_annee?: number
    a_annee?: number
    de?: number
    a?: number
    variation_relative_pct?: number
    justification?: { sens_souhaite: string; methode: string; source: string } | string
    raison?: string
  }
}
interface Realisations {
  millesime: string
  source: string
  avertissement: string
  programme: string
  libelle: string
  mission: string
  prevu_depense: { annees: Annee[]; lecture: string; note_perimetre: string; note?: string }
  resultats_mesures: { indicateurs: Indicateur[]; note: string | null; lecture: string }
  realisations_concretes: {
    liste: { objet: string; beneficiaire: string; montant_eur: number; type: string }[]
    millesime: string
    source: string
    note: string
    france2030: { total_eur: number; projets: number; millesime: string; note: string } | null
  }
  evaluations: { liens: { type: string; annee_execution: number; titre: string; url: string; verifie_le: string }[]; note: string | null; source: string }
}

// Libellés de tendance livrés par le pipeline, relatifs au sens souhaité publié par l'administration (charte docs/NEUTRALITE.md).
const CLASSE_TENDANCE: Record<string, string> = {
  'dans le sens souhaité publié': 'tendance-progres',
  'à l’inverse du sens souhaité publié': 'tendance-recul',
}

function justification(t: Indicateur['tendance']): string {
  if (typeof t.justification === 'string') return t.justification
  if (t.justification) return `sens souhaité « ${t.justification.sens_souhaite} » (${t.justification.methode}, ${t.justification.source})`
  return t.raison ?? ''
}

function carteIndicateur(i: Indicateur, cache: boolean): string {
  const t = i.tendance
  const derniere = [...i.valeurs].reverse().find((v) => v.valeur !== null)
  const cible = i.cibles.find((c) => c.valeur !== null && derniere && c.annee >= derniere.annee)
  return `<details class="carte"${cache ? ' data-plus hidden' : ''}>
  <summary>${h(i.sous_indicateur || i.indicateur)}${i.unite ? ` (${h(i.unite)})` : ''} : <span class="${CLASSE_TENDANCE[t.valeur] ?? ''}">&nbsp;${h(t.valeur)}</span></summary>
  <p><strong>${h(i.indicateur)}</strong>${i.indicateur_de_contexte ? ' <span class="badge">indicateur de contexte</span>' : ''}</p>
  <p class="aide">Objectif : ${h(i.objectif)}</p>
  <div class="tableau-defile"><table><caption>Valeurs réalisées et cibles</caption>
  <thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Réalisé</th><th scope="col" class="nombre">Cible</th></tr></thead>
  <tbody>${[...new Set([...i.valeurs.map((v) => v.annee), ...i.cibles.map((c) => c.annee)])]
    .sort()
    .map((a) => {
      const v = i.valeurs.find((x) => x.annee === a)
      const c = i.cibles.find((x) => x.annee === a)
      return `<tr><th scope="row">${a}</th><td class="nombre">${h(v?.brut ?? '')}</td><td class="nombre">${h(c?.brut ?? '')}</td></tr>`
    })
    .join('')}</tbody></table></div>
  <p>Tendance : <strong>${h(t.valeur)}</strong>${
    t.de_annee && t.a_annee ? ` entre ${t.de_annee} (${h(t.de)}) et ${t.a_annee} (${h(t.a)})${t.variation_relative_pct !== undefined ? `, ${h(pct(t.variation_relative_pct))}` : ''}` : ''
  }. Pourquoi : ${h(justification(t))}.</p>
  <p class="aide">Sens souhaité : ${h(i.sens_souhaite.valeur)}. ${h(i.sens_souhaite.justification)}${cible ? ` Prochaine cible : ${h(cible.brut)} en ${cible.annee}.` : ''}</p>
  <p class="source">${h([...new Set(i.valeurs.map((v) => v.source))].join(', '))}</p>
</details>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const p = params.get('p')
  if (!p || !/^\d{3}$/.test(p)) {
    cible.innerHTML = await choixProgramme('/decisions/realisations', 'Ce qui a été fait', 'Choisis un programme pour comparer le prévu et le dépensé année par année, suivre les indicateurs de résultat et lire les notes de la Cour des comptes.')
    brancherFiltre(cible)
    return
  }
  const r = await chargerSiPresent<Realisations>(`realisations/${p}.json`)
  if (!r) {
    cible.innerHTML = `<h1>Ce qui a été fait</h1>${absent(`Pas de données de réalisation pour le programme ${p}.`)}<p><a href="${lien('/decisions/realisations')}">Choisir un autre programme</a></p>`
    return
  }
  const annees = r.prevu_depense.annees
  const max = Math.max(...annees.map((a) => Math.max(a.vote_lfi_eur ?? 0, a.depense_constatee_eur ?? 0)))
  const tableau = `<div class="tableau-defile"><table><caption>Prévu (voté en loi de finances initiale) et dépensé, par année</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Voté</th><th scope="col" class="nombre">Dépensé</th><th scope="col" class="nombre">Écart</th></tr></thead>
<tbody>${annees
    .map((a) =>
      a.trou
        ? `<tr><th scope="row">${a.annee}</th><td colspan="3" class="absent">${h(a.trou)}</td></tr>`
        : `<tr><th scope="row">${a.annee}</th><td class="nombre">${a.vote_lfi_eur !== null ? h(eurLisible(a.vote_lfi_eur)) : 'non publié'}</td><td class="nombre">${
            a.depense_constatee_eur !== null ? h(eurLisible(a.depense_constatee_eur)) : 'non publié'
          }</td><td class="nombre">${a.ecart_pct !== null ? h((a.ecart_pct > 0 ? '+' : '') + pct(a.ecart_pct, 2)) : ''}</td></tr>`,
    )
    .join('')}</tbody></table></div>`
  const cle = annees.find((a) => typeof a.eur_sur_100 === 'number' && a.depense_constatee_eur !== null)
  const depenses = barres(
    annees.filter((a) => a.depense_constatee_eur !== null).map((a) => ({ nom: String(a.annee), valeur: a.depense_constatee_eur!, texte: eurLisible(a.depense_constatee_eur!) })),
    max,
    'Dépense constatée par année',
    -1,
  )
  const inds = r.resultats_mesures.indicateurs
  const tri = [...inds].sort((a, b) => Number(!!a.indicateur_de_contexte) - Number(!!b.indicateur_de_contexte))
  const comptes = inds.reduce<Record<string, number>>((s, i) => ((s[i.tendance.valeur] = (s[i.tendance.valeur] ?? 0) + 1), s), {})
  const rc = r.realisations_concretes
  cible.innerHTML = `
<h1>${h(r.libelle)}</h1>
<p class="chapeau">Programme ${h(r.programme)} · mission ${h(r.mission)}. Ce qui était prévu, ce qui a été dépensé, et ce que disent les indicateurs.</p>
<p><a href="${lien('/decisions/realisations')}">Choisir un autre programme</a></p>
<h2>Prévu et dépensé</h2>
${
  cle
    ? `<p class="carte" data-cle>Dépensé en ${cle.annee} : <strong>${surligne(eurLisible(cle.depense_constatee_eur!))}</strong>, soit ${h(sur100(cle.eur_sur_100!))} sur 100 € du budget de l’État.</p>`
    : ''
}
<div class="carte">${depenses}${tableau}<p class="aide">${h(r.prevu_depense.lecture)} ${h(r.prevu_depense.note_perimetre)}</p>${source('voir chaque année', r.millesime)}</div>
<h2>Résultats mesurés</h2>
<p class="avertissement">${h(r.avertissement)}</p>
${
  inds.length
    ? `<p>${inds.length} indicateurs : ${Object.entries(comptes)
        .map(([k, n]) => `${n} ${h(k)}`)
        .join(', ')}. ${h(r.resultats_mesures.lecture)}</p>
${tri.map((i, k) => carteIndicateur(i, k >= 12)).join('')}
${tri.length > 12 ? `<button type="button" id="plus-ind">Afficher les ${tri.length} indicateurs</button>` : ''}`
    : absent(r.resultats_mesures.note ?? 'Aucun indicateur publié.')
}
<h2>Réalisations concrètes</h2>
${
  rc.liste.length
    ? `<ul class="lignes">${rc.liste.map((x) => `<li><span>${h(x.objet)}</span><span class="montant">${h(eurLisible(x.montant_eur))}</span><span class="dest">${h(x.beneficiaire)} · ${h(x.type)}</span></li>`).join('')}</ul><p class="aide">${h(rc.note)}</p>${source(rc.source, rc.millesime)}`
    : absent(rc.note || 'Aucun objet financé nommé pour ce programme.')
}
${rc.france2030 ? `<p>France 2030 : ${h(eurLisible(rc.france2030.total_eur))} pour ${h(rc.france2030.projets)} projets (${h(rc.france2030.millesime)}). ${h(rc.france2030.note)}</p>` : ''}
<h2>Ce qu’en dit la Cour des comptes</h2>
${
  r.evaluations.liens.length
    ? `<ul>${r.evaluations.liens
        .map((l) => `<li><a href="${h(l.url)}" rel="noopener noreferrer">${h(l.titre)}</a> <span class="aide">(${h(l.type)}, lien vérifié le ${h(l.verifie_le)})</span></li>`)
        .join('')}</ul>${source(r.evaluations.source)}`
    : absent(r.evaluations.note ?? 'Aucune note de la Cour des comptes rattachée.')
}`
  cible.querySelector('#plus-ind')?.addEventListener('click', (e) => {
    cible.querySelectorAll<HTMLElement>('details[data-plus]').forEach((d) => (d.hidden = false))
    ;(e.target as HTMLElement).remove()
  })
}
