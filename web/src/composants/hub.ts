// Cartes d'un hub vers ses rayons, et sortie commune « Voir ta part personnelle ».
import { lien } from '../routeur'
import { rayons } from '../routes'
import { h } from '../util'
import { picto } from './pictos'

export function cartesRayons(parent: string, extra: { chemin: string; titre: string; resume: string }[] = []): string {
  const liste = [...rayons(parent).map((r) => ({ chemin: r.chemin, titre: r.titre, resume: r.resume ?? '', picto: r.picto })), ...extra.map((e) => ({ ...e, picto: undefined as string | undefined }))]
  return `<ul class="cartes">${liste
    .map((r) => `<li><a href="${lien(r.chemin)}"><strong>${r.picto ? picto(r.picto) : ''}<span>${h(r.titre)}</span></strong><span>${h(r.resume)}</span></a></li>`)
    .join('')}</ul>`
}

export const partPersonnelle = () =>
  `<p class="actions"><a class="bouton bouton-principal" href="#/calcul">Voir ta part personnelle</a></p>`
