// Pour les enseignants : trois activités prêtes à l'emploi (SES au lycée, enseignement moral et civique au collège et au
// lycée), chacune imprimable seule sur sa page. Page sans donnée chargée ; rien n'est stocké : le bouton « Imprimer cette
// activité » pose une classe le temps de l'impression (retirée à l'événement afterprint) puis appelle window.print().
// Rattachement aux programmes : grandes notions seulement ; aucun article de programme officiel n'est cité tant qu'il
// n'a pas été vérifié sur eduscol ou au Bulletin officiel (pages inaccessibles au robot lors de la rédaction, 20/11/2026).
import { versChemin } from '../chemins'
import { CONTACT } from '../composants/signaler'
import { h } from '../util'

export interface Activite {
  id: string
  titre: string
  famille: string
  niveau: string
  /** durée de la séance, en minutes */
  duree: number
  objectif: string
  notions: string[]
  /** pages du site à utiliser, adresses internes « #/… » */
  pages: { fragment: string; libelle: string }[]
  consigne: string[]
  /** trois questions ; celle d'index `questionSource` porte sur la source et la limite des données */
  questions: string[]
  questionSource: number
  vigilance: string
}

export const PRESENTATION =
  'Le billet découpé est un site citoyen gratuit, sans publicité ni traceur, qui montre où va l’argent public à partir de données publiques sourcées et datées ; il ne juge aucune dépense, ne prend parti pour personne, et aucune donnée saisie n’est envoyée ni conservée.'

export const ACTIVITES: Activite[] = [
  {
    id: 'activite-salaire',
    titre: 'Où va l’argent d’un salaire ?',
    famille: 'secu',
    niveau: 'Lycée : sciences économiques et sociales, ou enseignement moral et civique',
    duree: 55,
    objectif: 'Distinguer les prélèvements obligatoires versés sur un salaire (cotisations sociales, CSG et CRDS, impôt sur le revenu, TVA estimée) et nommer les organismes qui les reçoivent.',
    notions: ['prélèvements obligatoires', 'cotisations sociales et impôts', 'protection sociale', 'finances publiques'],
    pages: [
      { fragment: '#/calcul', libelle: 'Ton salaire' },
      { fragment: '#/suivre-un-euro', libelle: 'Suivre un euro' },
    ],
    consigne: [
      'Ouvre la page « Ton salaire ». Saisis le salaire net mensuel fictif donné par ton enseignant et la situation du foyer qu’il indique ; laisse vides les champs facultatifs.',
      'Sur la page « Ce que tu verses », recopie dans un tableau chaque prélèvement, son montant sur un an et l’organisme qui le reçoit.',
      'Dans le schéma « Le fil de l’euro », repère les grands destinataires de l’argent : Sécurité sociale, État, collectivités locales.',
      'Ouvre « Suivre un euro », choisis la CSG ou la TVA et note chaque étape, jusqu’au dernier niveau publié.',
      'Avec ton voisin, comparez les deux pistes : à quelle étape chacune s’arrête-t-elle, et pourquoi ?',
    ],
    questions: [
      'D’après le site, quelle différence y a-t-il entre une cotisation sociale et un impôt, dans la façon dont l’argent est affecté ?',
      'Quels organismes reçoivent les montants les plus élevés sur ce salaire fictif, et que financent-ils ?',
      'La TVA affichée est une estimation : à partir de quelles données publiques le site la calcule-t-il, et que ne peut-il pas savoir sur les achats d’un foyer ?',
    ],
    questionSource: 2,
    vigilance:
      'Impose un salaire fictif, le même pour toute la classe, ou deux ou trois salaires fictifs pour comparer. Ne demande jamais aux élèves le salaire de leurs parents ni le leur : même si le calcul se fait dans le navigateur et que rien n’est envoyé, un revenu réel reste une information personnelle devant la classe.',
  },
  {
    id: 'activite-commune',
    titre: 'Le budget de ma commune',
    famille: 'collectivites',
    niveau: 'Collège (cycle 4) et lycée : enseignement moral et civique ; lycée : sciences économiques et sociales',
    duree: 55,
    objectif: 'Lire le budget d’une commune, distinguer dépenses de fonctionnement et dépenses d’investissement, puis décrire une commune semblable avec les mêmes repères, la même année.',
    notions: ['finances publiques locales', 'collectivités territoriales', 'citoyenneté locale', 'décision publique'],
    pages: [{ fragment: '#/local/ma-commune', libelle: 'Ma commune en un écran' }],
    consigne: [
      'Ouvre « Ma commune en un écran » et cherche la commune de l’établissement, par son nom ou son code postal.',
      'Dans l’onglet de la commune, relève l’année des comptes, les dépenses de fonctionnement et les dépenses d’investissement.',
      'Explique avec tes mots la différence entre ces deux types de dépenses, avec un exemple pour chacun (le salaire des agents, la construction d’un équipement).',
      'Ouvre la partie « Communes semblables » et choisis une commune de même taille ou de même densité ; relève les mêmes montants, pour la même année.',
      'Présente les deux communes côte à côte, en euros par habitant, avec l’année et la source de chaque montant.',
    ],
    questions: [
      'Pourquoi compare-t-on des montants par habitant et pour la même année ?',
      'Quelles raisons peuvent expliquer que deux communes semblables n’aient pas les mêmes dépenses d’investissement une année donnée ? Lesquelles peut-on vérifier sur le site ?',
      'Quelle est la source des comptes affichés et de quelle année datent-ils ? Que ne disent-ils pas, par exemple sur ce que l’intercommunalité ou le département dépensent pour les mêmes habitants ?',
    ],
    questionSource: 2,
    vigilance:
      'Un écart entre deux communes ne dit pas laquelle est mieux gérée : taille, compétences confiées à l’intercommunalité, projets en cours ou emprunts changent les montants d’une année à l’autre. Le site ne classe pas les communes ; l’exercice consiste à décrire, pas à noter. Les budgets de la commune, de l’intercommunalité, du département et de la région ne s’additionnent pas.',
  },
  {
    id: 'activite-vote',
    titre: 'Comment se vote un impôt ?',
    famille: 'ue',
    niveau: 'Lycée : enseignement moral et civique, sciences économiques et sociales ; collège, en 3e',
    duree: 50,
    objectif: 'Suivre le chemin d’une règle fiscale : un article de loi de finances, le scrutin public qui s’y rapporte, le décompte des votes par groupe, et ce que ce vote permet ou non de conclure.',
    notions: ['rôle du Parlement', 'loi de finances', 'consentement à l’impôt (article 14 de la Déclaration des droits de l’homme et du citoyen de 1789)', 'citoyenneté'],
    pages: [{ fragment: '#/decisions/qui-a-vote', libelle: 'Qui a voté tes impôts' }],
    consigne: [
      'Ouvre « Qui a voté tes impôts » et choisis un impôt, par exemple la CSG ou l’impôt sur le revenu.',
      'Dans la liste des articles, choisis-en un : note le texte de loi, l’année et ce que l’article modifie, avec les mots de son intitulé officiel.',
      'Ouvre un scrutin public lié à cet impôt : note sa date, son objet et son résultat.',
      'Lis le décompte publié par groupe : pour chaque groupe, le nombre de députés pour, contre, qui se sont abstenus ou n’ont pas voté.',
      'Écris deux phrases : ce que ce scrutin établit, puis ce qu’il ne permet pas de savoir.',
    ],
    questions: [
      'Quelle différence y a-t-il entre le vote d’un article et le vote de la loi de finances dans son ensemble ?',
      'Pourquoi le décompte par groupe ne suffit-il pas pour connaître le vote de chaque député ? Où le site donne-t-il ce vote ?',
      'Quelle institution publie ces décomptes ? Le site n’affiche ni les votes à main levée ni les scrutins nominatifs du Sénat : que ne peut-on donc pas savoir sur un article adopté sans scrutin public ?',
    ],
    questionSource: 2,
    vigilance:
      'Garde la discussion sur la procédure, pas sur les positions des partis : tous les groupes sont présentés de la même façon, dans l’ordre alphabétique. Un vote sur un article ne résume pas la position d’un groupe sur l’impôt entier : un groupe peut voter contre un article puis pour la loi, ou l’inverse. Ne demande pas aux élèves leur opinion politique ni celle de leur famille.',
  },
]

/** Adresse lisible d'une page, à recopier au tableau ou depuis la feuille imprimée (« site.fr/calcul/ »). */
const adresseLisible = (fragment: string) => `${__ADRESSE_SITE__}/${versChemin(fragment)}`

function fiche(a: Activite, i: number): string {
  const idTitre = `${a.id}-titre`
  return `<section class="fiche f-${h(a.famille)}" id="${h(a.id)}" aria-labelledby="${idTitre}">
<div class="fiche-tete">
  <p class="fiche-numero">Activité ${i + 1} sur ${ACTIVITES.length}</p>
  <h2 id="${idTitre}">${h(a.titre)}</h2>
  <dl class="fiche-infos">
    <div><dt>Niveau et matière</dt><dd>${h(a.niveau)}</dd></div>
    <div><dt>Durée</dt><dd>${a.duree} minutes</dd></div>
    <div><dt>${a.pages.length > 1 ? 'Pages à utiliser' : 'Page à utiliser'}</dt><dd><ul class="fiche-pages">${a.pages
      .map((p) => `<li><a href="${h(p.fragment)}">${h(p.libelle)}</a> <span class="fiche-adresse">${h(adresseLisible(p.fragment))}</span></li>`)
      .join('')}</ul></dd></div>
  </dl>
</div>
<div class="fiche-corps">
  <p class="fiche-objectif"><strong>Objectif.</strong> ${h(a.objectif)}</p>
  <p class="aide">Notions travaillées : ${a.notions.map(h).join(', ')}.</p>
  <h3>Consigne pour les élèves</h3>
  <ol class="fiche-etapes">${a.consigne.map((c) => `<li>${h(c)}</li>`).join('')}</ol>
  <h3>Questions de fin</h3>
  <ol class="fiche-questions">${a.questions
    .map((q, n) => (n === a.questionSource ? `<li class="question-source">${h(q)} <span class="aide">(source et limite des données)</span></li>` : `<li>${h(q)}</li>`))
    .join('')}</ol>
  <aside class="fiche-vigilance" aria-labelledby="${a.id}-vigilance">
    <h3 id="${a.id}-vigilance">Point de vigilance pour l’enseignant</h3>
    <p>${h(a.vigilance)}</p>
  </aside>
  <p class="actions"><button type="button" class="bouton-secondaire" data-imprimer="${h(a.id)}">Imprimer cette activité</button></p>
</div>
</section>`
}

/** Imprime une seule activité : classe posée le temps de l'impression, retirée à afterprint (rien n'est stocké). */
export function imprimerActivite(racine: HTMLElement, id: string) {
  const nettoyer = () => {
    document.body.classList.remove('impression-une-activite')
    racine.querySelectorAll('.fiche-imprimee').forEach((f) => f.classList.remove('fiche-imprimee'))
  }
  nettoyer()
  const f = racine.querySelector<HTMLElement>(`.fiche[id="${id}"]`)
  if (!f) return
  f.classList.add('fiche-imprimee')
  document.body.classList.add('impression-une-activite')
  window.addEventListener('afterprint', nettoyer, { once: true })
  window.print()
}

export function rendre(cible: HTMLElement) {
  cible.innerHTML = `<div class="enseignants">
<div class="enseignants-tete">
  <h1>Pour les enseignants</h1>
  <p class="chapeau">${h(PRESENTATION)}</p>
  <p>Trois activités prêtes à l’emploi pour une séance de sciences économiques et sociales au lycée ou d’enseignement moral et civique au collège et au lycée. Chacune donne une consigne en étapes, trois questions de fin et un point de vigilance, et s’imprime seule sur sa page.</p>
  <nav aria-label="Les trois activités">
    <ol class="enseignants-sommaire">${ACTIVITES.map((a) => `<li><a href="#${h(a.id)}">${h(a.titre)}</a> <span class="aide">${a.duree} minutes</span></li>`).join('')}</ol>
  </nav>
  <p class="aide">Pour imprimer les trois activités d’un coup, utilise l’impression du navigateur : chacune commence sur une nouvelle page, sans menus ni boutons.</p>
</div>
${ACTIVITES.map(fiche).join('\n')}
<div class="enseignants-pied">
  <h2>Programmes et contact</h2>
  <p>Chaque activité est rattachée à de grandes notions (prélèvements obligatoires, finances publiques, rôle du Parlement, citoyenneté). Le site ne cite pas d’article de programme : pour le rattachement précis, reporte-toi au programme en vigueur de ton niveau, publié au Bulletin officiel et sur eduscol.</p>
  <p>Une question, une erreur, une activité à proposer ? Écris à <span class="enseignants-contact">${h(CONTACT)}</span>. C’est la même adresse que dans les <a href="#/mentions">mentions légales</a>.</p>
  <p><a class="bouton-lien" href="#/methode">Méthode et sources du site</a></p>
</div>
</div>`
  cible.querySelectorAll<HTMLButtonElement>('button[data-imprimer]').forEach((b) => b.addEventListener('click', () => imprimerActivite(cible, b.dataset.imprimer!)))
}
