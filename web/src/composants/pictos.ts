// Pictos maison (maquette W_Systeme) : grille de 24, trait de 2,2 à bouts ronds, sans remplissage,
// posés dans un rond à contour. Toujours décoratifs : un libellé les accompagne.
const TRACES: Record<string, string> = {
  sante: '<path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/>',
  retraites: '<path d="M3 18h18M6 18a6 6 0 0 1 12 0M12 5v3M4.5 9.5l2 2M19.5 9.5l-2 2"/>',
  ecole: '<path d="M12 6c-2-1.5-5-2-9-2v14c4 0 7 .5 9 2 2-1.5 5-2 9-2V4c-4 0-7 .5-9 2zM12 6v14"/>',
  defense: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  justice: '<path d="M12 4v16M7 20h10M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z"/>',
  dette: '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
  transports: '<rect x="5" y="3" width="14" height="14" rx="3"/><path d="M5 11h14M8 21l2-4M16 21l-2-4M9 14h.01M15 14h.01"/>',
  logement: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M10 21v-6h4v6"/>',
  culture: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  europe: [0, 1, 2, 3, 4, 5, 6, 7]
    .map((i) => `<circle class="plein" cx="${(12 + 8 * Math.cos((i * Math.PI) / 4)).toFixed(1)}" cy="${(12 + 8 * Math.sin((i * Math.PI) / 4)).toFixed(1)}" r="1.3"/>`)
    .join(''),
  commune: '<path d="M4 21V10h16v11M2 21h20M9 21v-5h6v5M12 10V3M12 3h5v3h-5"/>',
  entreprises: '<path d="M3 21V9l6 4V9l6 4V4h6v17z"/>',
  etat: '<path d="M3 21h18M5 21V10M9.5 21V10M14.5 21V10M19 21V10M3 10l9-6 9 6z"/>',
  secu: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
  niches: '<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.6"/><circle cx="17" cy="17" r="2.6"/>',
  operateurs: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
  menages: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><circle cx="17.5" cy="9" r="2.5"/><path d="M17 14.5c2.8 0 4.8 2 4.8 5"/>',
  calcul: '<rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M8.5 7.5h7M8.5 12h.01M12 12h.01M15.5 12h.01M8.5 16h.01M12 16h.01M15.5 16h.01"/>',
  recettes: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
  vote: '<path d="M4 12h16v8H4zM8 12V5h8v7M10 8.5l1.5 1.5 3-3"/>',
  controle: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
  methode: '<path d="M6 3h9l4 4v14H6zM15 3v4h4M9 12h7M9 16h7"/>',
  fait: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
}

export type Picto = keyof typeof TRACES

/** Rond à contour avec son picto ; classe « picto-grand » pour le titre d'une page. */
export function picto(nom: string, classe = ''): string {
  const t = TRACES[nom]
  if (!t) return ''
  return `<span class="picto${classe ? ' ' + classe : ''}" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false">${t}</svg></span>`
}

export const LOGO = (classe = 'logo') =>
  `<svg class="${classe}" width="40" height="34" viewBox="0 0 40 34" aria-hidden="true" focusable="false"><rect class="l-papier" x="1.5" y="5" width="9" height="24" rx="3.5" stroke-width="2.5"/><rect class="l-secu" x="13" y="2" width="12" height="24" rx="3.5" stroke-width="2.5"/><rect class="l-etat" x="27.5" y="8" width="5" height="24" rx="2.5" stroke-width="2.5"/><rect class="l-coll" x="35" y="4" width="3.5" height="24" rx="1.75" stroke-width="2"/></svg>`
