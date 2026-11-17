// Sélecteur de programme (liste issue de l'arbre d'exécution 2024), avec filtre texte.
import { listeProgrammes } from '../donnees'
import { lien } from '../routeur'
import { h, libelle, md } from '../util'

export async function choixProgramme(chemin: string, titre: string, intro: string): Promise<string> {
  const progs = await listeProgrammes()
  progs.sort((a, b) => b.md - a.md)
  return `<h1>${h(titre)}</h1>
<p class="chapeau">${h(intro)}</p>
<label for="filtre-prog">Chercher un programme (nom ou numéro)</label>
<input id="filtre-prog" type="search" autocomplete="off" />
<ul class="lignes" id="liste-prog">${progs
    .map(
      (p) =>
        `<li data-t="${h((p.numero + ' ' + p.nom + ' ' + p.mission + ' ' + libelle(p.poste)).toLowerCase())}"><a href="${lien(chemin, { p: p.numero })}">${h(p.nom)}</a><span class="montant">${h(md(p.md))}</span><span class="dest">Programme ${h(p.numero)} · ${h(p.mission)} · ${h(libelle(p.poste))}</span></li>`,
    )
    .join('')}</ul>`
}

export function brancherFiltre(cible: HTMLElement) {
  const f = cible.querySelector<HTMLInputElement>('#filtre-prog')
  f?.addEventListener('input', () => {
    const q = f.value.trim().toLowerCase()
    cible.querySelectorAll<HTMLElement>('#liste-prog li').forEach((li) => {
      li.hidden = !!q && !(li.dataset.t ?? '').includes(q)
    })
  })
}
