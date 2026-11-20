// Titres et descriptions des pages (balises title, meta description, Open Graph, JSON-LD), une seule source.
// Règles (docs/SEO.md, « Titres et descriptions ») : titre de 60 caractères au plus, nom du site en suffixe seulement
// s'il tient dans cette longueur (absent des pages profondes au titre long) ; description de 120 à 155 caractères ;
// uniques par page ; formulation neutre (docs/lexique_neutre.json), avec le terme qu'un citoyen chercherait.
// Les pages paramétrées (commune, département) passent par metaCommune et metaDepartement. Contrôle sur toutes les
// pages prérendues : web/tests/metadonnees.test.ts.

export const NOM_SITE = 'Le billet découpé'
export const TITRE_ACCUEIL = 'Le billet découpé : vois où va l’argent que tu verses'
export const TITRE_MAX = 60
export const DESCRIPTION_MIN = 120
export const DESCRIPTION_MAX = 155
const SUFFIXE = ` · ${NOM_SITE}`

/** Titre du document : le nom du site en suffixe s'il tient dans TITRE_MAX, sinon le titre seul. */
export const titreSite = (base: string) => (base.length + SUFFIXE.length <= TITRE_MAX ? base + SUFFIXE : base)

/** Premier candidat dont la longueur est dans [min, max] ; à défaut le premier qui ne dépasse pas max ; sinon le dernier. */
export function ajuster(candidats: string[], min: number, max: number): string {
  return candidats.find((c) => c.length >= min && c.length <= max) ?? candidats.find((c) => c.length <= max) ?? candidats[candidats.length - 1]
}

/** « de Nantes », « d’Angers », « du Mans », « des Abymes ». */
export function deCommune(nom: string): string {
  if (/^Le /.test(nom)) return `du ${nom.slice(3)}`
  if (/^Les /.test(nom)) return `des ${nom.slice(4)}`
  return /^[AEIOUYÀÂÉÈÊËÎÏÔÛÙŒ]/i.test(nom) ? `d’${nom}` : `de ${nom}`
}

const nombre = (x: number) => new Intl.NumberFormat('fr-FR').format(x)

/** Page d'une commune : « Budget de Nantes (44) : dépenses, dotations, impôts locaux ». */
export function metaCommune(nom: string, codeDepartement: string, departement: string, population: number) {
  const de = deCommune(nom)
  const objet = 'dépenses par habitant, dette, dotations de l’État et taux d’impôts locaux votés'
  return {
    titre: ajuster([`Budget ${de} (${codeDepartement}) : dépenses, dotations, impôts locaux`, `Budget ${de} (${codeDepartement}) : dépenses, impôts locaux`, `Budget ${de} (${codeDepartement})`, `${nom} (${codeDepartement})`], 0, TITRE_MAX),
    description: ajuster(
      [
        `Budget ${de} (${departement}, ${nombre(population)} habitants) : ${objet}, avec leurs sources publiques.`,
        `Budget ${de} (${departement}, ${nombre(population)} habitants) : ${objet}, avec leurs sources.`,
        `Budget ${de} (${departement}, ${nombre(population)} habitants) : ${objet}.`,
        `Budget ${de} (${codeDepartement}, ${nombre(population)} habitants) : ${objet}.`,
        `Budget ${de} (${codeDepartement}) : ${objet}.`,
      ],
      DESCRIPTION_MIN,
      DESCRIPTION_MAX,
    ),
  }
}

/** Page d'un département : « Loire-Atlantique (44) : budget des communes et du département ». */
export function metaDepartement(nom: string, code: string, communes: number) {
  return {
    titre: ajuster([`${nom} (${code}) : budget des communes et du département`, `${nom} (${code}) : budget des communes`], 0, TITRE_MAX),
    description: ajuster(
      [
        `${nom} (${code}) : budget du département et de ses ${nombre(communes)} communes, dépenses par habitant, dotations de l’État et taux d’impôts locaux votés.`,
        `${nom} (${code}) : budget du département et de ses ${nombre(communes)} communes, dépenses, dotations de l’État et taux d’impôts locaux votés.`,
        `${nom} (${code}) : budget du département et de ses ${nombre(communes)} communes, dépenses, dotations et taux d’impôts locaux.`,
      ],
      DESCRIPTION_MIN,
      DESCRIPTION_MAX,
    ),
  }
}

/**
 * Pages fixes, par chemin de route (src/routes.ts) : titre sans le nom du site (titreSite l'ajoute s'il tient) et
 * description. L'accueil garde TITRE_ACCUEIL. Une route absente d'ici reprend titrePage (ou titre) et description de la
 * table des routes, et le contrôle des longueurs le signale.
 */
export const META_PAGES: Record<string, { titre?: string; description: string }> = {
  '/': { description: 'Site citoyen : à partir de ton salaire net, vois ce que tu verses en impôts et cotisations, à qui, et où va l’argent public. Calcul fait sur ton appareil.' },
  '/calcul': { titre: 'Combien je verse d’impôts : calcul à partir du salaire', description: 'Indique ton salaire net : le site calcule ce que tu verses en un an en cotisations, CSG, impôt sur le revenu, TVA et impôts locaux, sur ton appareil.' },
  '/calcul/resultat': { titre: 'Ce que tu verses', description: 'Résultat du calcul fait sur ton appareil : ce que tu verses en un an, par prélèvement et par destinataire, après la saisie de ton salaire net.' },
  '/calcul/bulletin': { titre: 'Fiche de paie expliquée : cotisations, CSG, impôt', description: 'Chaque ligne d’une fiche de paie calculée sur ton appareil : cotisations, CSG, CRDS, prélèvement à la source, net à payer et organisme qui reçoit l’argent.' },
  '/calcul/recu': { titre: 'Ton reçu de l’année : à imprimer ou partager', description: 'Ton reçu de l’année : ce que tu verses, une ligne par destinataire, à imprimer ou partager, sans montants par défaut. Rien n’est envoyé.' },
  '/calcul/et-si': { titre: 'Et si mon salaire changeait ? Impôts et cotisations', description: 'Compare deux salaires : ce que tu verserais en cotisations, CSG, CRDS et impôt sur le revenu, à qui cela irait, et ce que deviennent 100 € bruts de plus.' },
  '/explorer': { titre: 'Dépenses publiques en France : à quoi sert l’argent', description: 'Les dépenses publiques en France par grand ensemble : État, Sécurité sociale, collectivités locales, Union européenne, recettes et dette, avec sources.' },
  '/explorer/etat': { titre: 'Budget de l’État : sur 100 € dépensés', description: 'Sur 100 € dépensés par l’État : école, défense, dette, solidarité et autres postes du budget, dépensé, voté ou proposé, et la part payée par l’emprunt.' },
  '/explorer/etat/detail': { titre: 'Budget de l’État en détail : missions et programmes', description: 'Le budget de l’État ligne par ligne : missions, programmes et actions, en milliards d’euros, jusqu’à la ligne votée en loi de finances, avec la source.' },
  '/explorer/secu': { titre: 'Budget de la Sécurité sociale et protection sociale', description: 'Les dépenses de la Sécurité sociale et de la protection sociale : retraites, santé, famille, chômage, prestations versées et organismes qui les financent.' },
  '/explorer/collectivites': { titre: 'Budget des collectivités locales', description: 'Communes, intercommunalités, départements et régions : leurs dépenses, leurs recettes et ce que l’État leur verse, d’après les comptes publics publiés.' },
  '/explorer/ue': { titre: 'Budget de l’Union européenne : ce que verse la France', description: 'Ce que la France verse au budget de l’Union européenne, ce qui revient en France et qui le reçoit, par fonds et par département, avec les sources.' },
  '/explorer/recettes': { titre: 'Recettes publiques : TVA, impôt sur le revenu, CSG', description: 'Les recettes publiques depuis 2005 : TVA, impôt sur le revenu, CSG, cotisations sociales et autres prélèvements, avec l’administration qui encaisse chacun.' },
  '/explorer/dette': { titre: 'Dette publique de la France : encours et intérêts', description: 'La dette publique de la France : encours, intérêts payés chaque année, part du PIB et détenteurs de la dette, d’après les comptes publiés par l’Insee.' },
  '/explorer/operateurs': { titre: 'Les opérateurs de l’État : agences et établissements', description: 'Les opérateurs de l’État (universités, agences régionales de santé, agences de l’eau, établissements publics) : ce que l’État leur verse et leurs emplois.' },
  '/explorer/niches': { titre: 'Dépenses fiscales et exonérations de cotisations', description: 'Les dépenses fiscales (souvent appelées niches fiscales) et les exonérations de cotisations, mesure par mesure : montant estimé, bénéficiaires et source.' },
  '/explorer/retraites': { titre: 'Retraites : montants, régimes et financement', description: 'Les retraites en France : pensions versées chaque année, régimes, nombre de retraités, pension moyenne et origine de l’argent, avec la source des chiffres.' },
  '/explorer/fonction-publique': { titre: 'Fonction publique : nombre d’agents et dépenses', description: 'Combien de personnes travaillent pour l’État, les collectivités locales et les hôpitaux publics, et ce que l’État dépense pour ses agents sur 100 €.' },
  '/explorer/education-recherche': { titre: 'Budget de l’éducation et de la recherche', description: 'Dépenses publiques pour l’école, l’enseignement supérieur et la recherche : qui dépense, combien, ce que des régions versent aux lycées, avec sources.' },
  '/explorer/aide-developpement': { titre: 'Aide publique au développement : montant et pays', description: 'L’aide publique au développement de la France : montant déclaré, dons et prêts, pays qui la reçoivent, organismes qui la versent, part du budget de l’État.' },
  '/explorer/hopitaux': { titre: 'Hôpitaux, cliniques et EHPAD : financement et comptes', description: 'Qui verse de l’argent aux hôpitaux, cliniques et EHPAD (assurance maladie, État, départements), leurs comptes publiés et la recherche d’un établissement.' },
  '/explorer/justice-defense': { titre: 'Budget de la justice et de la défense', description: 'Budget de la justice et de la défense : tribunaux, prisons, aide juridictionnelle, armées, équipements, opérations et emplois, sur 100 € de l’État.' },
  '/explorer/prestations': { titre: 'Prestations sociales : allocations, RSA, APL, chômage', description: 'Allocations familiales, aides au logement, RSA, prime d’activité, AAH, minimum vieillesse, chômage : montants versés par an, foyers et financeurs.' },
  '/explorer/etat-actionnaire': { titre: 'L’État actionnaire : entreprises et dividendes', description: 'Les entreprises dont l’État est actionnaire : dividendes reçus, apports en capital, cessions et valeur des participations par année, avec les sources.' },
  '/explorer/fonds-europeens': { titre: 'Fonds européens en France : par fonds, région, thème', description: 'Ce que l’Union européenne finance en France par ses fonds régionaux, social, rural et pour la pêche : prévu, décidé, payé, par région, thème et année.' },
  '/explorer/solidarites-departements': { titre: 'Solidarités des départements : RSA, autonomie, enfance', description: 'RSA, autonomie, handicap, aide sociale à l’enfance : ce que versent les départements, leurs bénéficiaires et les recettes reçues pour ces aides.' },
  '/explorer/numerique-etat': { titre: 'Numérique de l’État : grands projets informatiques', description: 'Grands projets informatiques de l’État : coût estimé et durée prévue à chaque édition publiée, ministère qui les conduit, fonds pour le numérique.' },
  '/explorer/outre-mer': { titre: 'Dépenses de l’État dans les collectivités d’outre-mer', description: 'Ce que l’État dépense dans six territoires d’outre-mer, de Saint-Pierre-et-Miquelon à la Nouvelle-Calédonie : par territoire, mission et habitant.' },
  '/explorer/formation-professionnelle': { titre: 'Formation professionnelle : CPF, alternance, financeurs', description: 'La formation professionnelle en France : compte personnel de formation, alternance, formation des demandeurs d’emploi, montants publiés et financeurs.' },
  '/explorer/recouvrement': { titre: 'Collecte des impôts et cotisations, contrôle et fraude', description: 'Qui collecte les impôts et les cotisations, frais de gestion publiés, montants notifiés et encaissés après contrôle, et estimations publiées de la fraude.' },
  '/explorer/comparaison-europe': { titre: 'Dépense publique et impôts : la France et l’Europe', description: 'Dépense publique, impôts et cotisations de la France et des autres pays de l’Union européenne : part du PIB, euros par habitant, grandes fonctions.' },
  '/explorer/series': { titre: 'Finances publiques depuis 2005 : dépenses, dette, solde', description: 'Recettes, dépenses par administration et par fonction, solde, dette et intérêts publics depuis 2005, en euros courants, constants ou en part du PIB.' },
  '/suivre-un-euro': { titre: 'Suivre un euro d’impôt, étape par étape', description: 'Suis 1 € de CSG, d’impôt sur le revenu, de cotisation retraite ou de TVA, de l’organisme qui le reçoit jusqu’au dernier niveau publié, étape par étape.' },
  '/local': { titre: 'Budget de ma commune : dépenses, dette, impôts locaux', description: 'Budget de ma commune : dépenses, dette, dotations de l’État et taux d’impôts locaux votés, pour chaque commune, son intercommunalité et son département.' },
  '/local/departement': { titre: 'Les communes d’un département', description: 'Les communes d’un département et leur budget : dépenses par habitant, dotations de l’État et taux d’impôts locaux votés. La page s’affiche après le choix.' },
  '/local/commune': { titre: 'Ta commune', description: 'Le budget d’une commune choisie par son code Insee : dépenses, dotations de l’État, taux d’impôts locaux votés, subventions publiées, après le choix.' },
  '/local/comparer': { titre: 'Comparer le budget de deux communes', description: 'Deux communes côte à côte, aux mêmes échelles : dépenses, recettes et dette par habitant, épargne, investissement, versements de l’État, taux votés.' },
  '/local/croiser': { titre: 'Communes semblables : densité, population, budget', description: 'Des communes de même densité, de même taille ou de même place autour d’une ville : leurs dépenses, dette, dotations et taux, la même année.' },
  '/local/projets': { titre: 'Projets subventionnés par l’État dans ma commune', description: 'Les projets d’une commune ou d’un département subventionnés par l’État : dotations d’investissement et Fonds vert, par année, bénéficiaire et montant.' },
  '/local/ma-commune': { titre: 'Ma commune par code postal : budgets et projets', description: 'Ton code postal ou ta commune : budgets de la commune, de l’intercommunalité, du département et de la région, bénéficiaires, projets, communes semblables.' },
  '/beneficiaires': { titre: 'Qui reçoit l’argent public : subventions, marchés', description: 'Qui reçoit l’argent de l’État : subventions, marchés publics et aides publiées en données ouvertes, par programme du budget et par bénéficiaire.' },
  '/beneficiaires/programme': { titre: 'Un programme du budget de l’État en détail', description: 'Un programme du budget de l’État en détail : nature de la dépense, crédits votés et dépensés, effectifs et bénéficiaires publiés, avec les sources.' },
  '/beneficiaires/subventions': { titre: 'Subventions de l’État : montants et bénéficiaires', description: 'Les subventions versées par l’État et ses opérateurs : montants par année, par ministère ou organisme, par type de bénéficiaire, recherche par nom.' },
  '/beneficiaires/marches': { titre: 'Marchés publics : montants, acheteurs et titulaires', description: 'Les marchés publics de 2019 à 2025 : montants par année, type d’achat, acheteur, secteur et région, principaux titulaires, montants écartés et leur règle.' },
  '/beneficiaires/organisation': { titre: 'Argent public reçu par une association ou entreprise', description: 'Cherche une association, une entreprise, une commune ou un établissement public par nom ou SIREN : l’argent public reçu, source par source et par année.' },
  '/decisions': { titre: 'Qui décide et contrôle la dépense publique', description: 'Qui décide et qui contrôle la dépense publique : votes du Parlement, crédits dépensés, rapports des juridictions financières, financement des partis.' },
  '/decisions/votes': { titre: 'Budget voté : amendements et mouvements de crédits', description: 'Budget de l’État : ce que le Parlement a voté, les amendements adoptés et les mouvements de crédits décidés en cours d’année, programme par programme.' },
  '/decisions/realisations': { titre: 'Budget de l’État : crédits prévus et dépensés', description: 'Pour chaque programme du budget de l’État : crédits prévus, crédits dépensés, indicateurs de résultat publiés et notes d’exécution de la Cour des comptes.' },
  '/decisions/controle': { titre: 'Contrôle des comptes publics et représentants d’intérêts', description: 'Rapports des chambres régionales des comptes, représentants d’intérêts déclarés à la HATVP et aides aux entreprises selon les études publiées.' },
  '/decisions/vie-politique': { titre: 'Financement des partis et comptes de campagne', description: 'Financement de la vie politique : aide publique aux partis, comptes de campagne des candidats par élection, d’après la CNCCFP et le Journal officiel.' },
  '/decisions/resultats': { titre: 'Résultats des programmes de l’État : cibles et mesures', description: 'Pour chaque programme du budget de l’État : cible annoncée et valeur mesurée des indicateurs, crédits dépensés, et par département le baromètre publié.' },
  '/decisions/application-des-lois': { titre: 'Application des lois : décrets prévus et publiés', description: 'Pour chaque loi depuis 2002 : mesures d’application prévues, décrets publiés, mesures en attente et délais, d’après l’Assemblée nationale et LexImpact.' },
  '/decisions/qui-a-vote': { titre: 'Qui a voté mes impôts : TVA, CSG, impôt sur le revenu', description: 'Qui a voté la TVA, la CSG ou l’impôt sur le revenu : articles des lois de finances, scrutins publics, vote de chaque député, amendements depuis 2024.' },
  '/demarche': { titre: 'La démarche : site citoyen, non officiel et gratuit', description: 'La démarche du site : un projet citoyen, non officiel, gratuit et sans publicité, qui ne soutient aucun parti et présente chaque sujet de la même façon.' },
  '/methode': { titre: 'Méthode et sources des données publiques', description: 'Méthode et sources : comment chaque montant est calculé, d’où viennent les données publiques utilisées et à quelle date le site les a collectées.' },
  '/methode/tracabilite': { titre: 'Traçabilité : d’où vient chaque montant', description: 'Traçabilité des dépenses de l’État : la part de l’argent dont le destinataire est publié en données ouvertes, bloc par bloc, avec la source des montants.' },
  '/methode/limites': { titre: 'Limites connues des données', description: 'Les limites connues du site : ce que les données publiques ne permettent pas de dire, les sources non publiées et les estimations signalées comme telles.' },
  '/mentions': { titre: 'Mentions légales et confidentialité', description: 'Mentions légales et confidentialité du site : éditeur, hébergeur, données personnelles, aucun cookie, aucune mesure d’audience, aucune saisie envoyée.' },
  '/methode/fraicheur': { titre: 'Fraîcheur des données : collecte et millésime', description: 'Pour chaque source publique utilisée : date de la dernière collecte, année couverte, date de publication par la source, prochaine édition et statut.' },
  '/methode/glossaire': { titre: 'Glossaire : sigles et mots du budget', description: 'Glossaire des sigles et des mots du budget public (LFI, PLF, CSG, ONDAM…) : définitions courtes en langage courant, avec la source officielle de chacune.' },
  '/enseignants': { titre: 'Pour les enseignants : trois activités pour la classe', description: 'Trois activités pour les cours de sciences économiques et sociales et d’enseignement moral et civique : salaire fictif, budget communal, vote d’un impôt.' },
  '/recherche': { titre: 'Rechercher une commune, un programme, une page', description: 'Recherche dans tout le site : pages, communes, départements, missions et programmes du budget de l’État, opérateurs, prestations. Faite sur ton appareil.' },
  '/introuvable': { titre: 'Page introuvable', description: 'Cette adresse ne correspond à aucune page du site « Le billet découpé ». Le calcul, le budget de l’État et le budget de chaque commune restent accessibles.' },
}
