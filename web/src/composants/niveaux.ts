// Couleurs par niveau de collectivité (audit design du 19/11, problème 13) : une teinte par niveau dans la famille
// « collectivités » (sarcelles), jetons --niveau-* de styles.css, 3:1 au moins sur le fond et le papier dans les deux
// modes (tests/contrastes.test.ts). La couleur ne porte jamais le sens seule : la pastille accompagne toujours le nom
// du niveau, et elle est cachée aux lecteurs d'écran (le nom suffit).
export type NiveauCollectivite = 'commune' | 'epci' | 'departement' | 'region'

export const NIVEAUX: Record<NiveauCollectivite, string> = {
  commune: 'Commune',
  epci: 'Intercommunalité',
  departement: 'Département',
  region: 'Région',
}

/** Destinataires des prélèvements (calcul, affectation.json) qui sont un niveau de collectivité. */
const PAR_DESTINATAIRE: Record<string, NiveauCollectivite> = {
  commune: 'commune',
  epci: 'epci',
  departement: 'departement',
  region: 'region',
  region_idf: 'region',
}

export function niveauDestinataire(id: string): NiveauCollectivite | null {
  return PAR_DESTINATAIRE[id] ?? null
}

/** Pastille de couleur du niveau (contour encre, 1 rem), décorative. */
export function pastilleNiveau(n: NiveauCollectivite | null | undefined): string {
  return n ? `<span class="pastille-niveau" data-niveau="${n}" aria-hidden="true"></span>` : ''
}
