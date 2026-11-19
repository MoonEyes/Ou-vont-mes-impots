# Charte de neutralité

Le site ne soutient aucun parti, aucun candidat ni aucune position sur le niveau des impôts ou des dépenses. Il n'est ni pour ni contre l'impôt : il donne des montants, leurs sources et leurs limites.

## Références

- Effet de cadrage (Tversky et Kahneman, « The Framing of Decisions and the Psychology of Choice », 1981) : la même somme présentée comme une perte (« ce que tu paies ») ou comme un gain (« ce que tu finances ») oriente le jugement. Le site garde un seul cadrage neutre.
- Effet de média hostile (Vallone, Ross et Lepper, 1985) : chaque camp perçoit un biais contre lui dans un même texte. Seule parade : des mots sans valeur, des formats identiques, des règles d'ordre affichées.
- Réactance (Brehm, 1966) : un texte qui pousse à une conclusion provoque le rejet du chiffre lui-même.
- Pluralisme et équilibre : principes de l'Arcom (équité de traitement entre partis, présentation honnête des questions controversées).
- Présentation des chiffres : pratiques des Décodeurs (Le Monde), de Full Fact et de The Markup (méthode publiée, chiffre avec sa base et sa source, pas d'adjectif à la place d'une comparaison).

## Règles (chacune vérifiée par un test)

| N° | Règle | Test |
|----|-------|------|
| 1 | Aucun soutien ni opposition : la page « La démarche » le dit en toutes lettres. | `ecrans.test.ts`, « la démarche » |
| 2 | Lexique neutre dans tout le texte affiché (pages, en-tête, pied, attributs, métadonnées, image de partage) : pas de minimisation ou d'amplification (« seulement 3 % »), d'adjectif d'intensité, de jugement (« gaspillage », « cadeau »), de verbe imagé (« engloutit », « pèse »), de « coûteux », de « trop ». | `ecrans.test.ts`, « lexique neutre » |
| 3 | Un seul cadrage pour l'argent du foyer : « ce que tu verses ». Jamais « ce que tu paies » ni « ce que tu finances ». | idem (entrée « cadrage incohérent ») |
| 4 | « Niche » n'apparaît qu'avec sa définition : « dépense fiscale (souvent appelée niche fiscale) ». | idem (règle « niche sans définition ») |
| 5 | Même format pour chaque sujet : montant en euros, « sur 100 € », source, millésime, part tracée et écarts ; un seul chiffre surligné par écran. | `ecrans.test.ts`, « règles 1, 5 et surligneur » |
| 6 | Partis, candidats, amendements : même tableau pour tous, aucune ligne mise en avant, ordre neutre écrit sous la liste (partis : aide totale fixée par la loi, puis alphabétique ; candidats : circonscription puis nom ; amendements : date). | `ecrans.test.ts`, « partis et candidats » |
| 7 | Couleurs sans valeur morale : pas de vert « bon » ni de rouge « mauvais » ; tendances et réductions dans la couleur du texte, le libellé porte le sens. Statuts de traçabilité codés trois fois (motif, libellé, couleur). | `regles.test.ts`, « neutralité : couleurs » ; « règle 2 » |
| 8 | Équilibre de la sélection : une page consacrée aux entreprises ou aux organismes renvoie aux sommes versées aux ménages (Sécurité sociale), avec le même format. | `ecrans.test.ts`, « partis et candidats » (bloc équilibre) |
| 9 | La part « non publiée » est décrite comme un état de la publication, jamais comme un soupçon sur l'usage de l'argent. La représentation d'intérêts est nommée avec le terme de la HATVP, sans « influence » ni « visés ». | `ecrans.test.ts`, « la démarche » et « lexique neutre » |
| 10 | Aucun code visuel institutionnel (Marianne, bleu et rouge de l'État, DSFR) ; mention « Site citoyen, non officiel » dans l'en-tête. | `regles.test.ts`, « aucun code visuel institutionnel » |
| 11 | Chiffre calculé par le site (ratio, différence, somme, moyenne, part) : affiché seulement si tous ses montants portent sur la même année et le même périmètre, avec sa méthode écrite à côté et le badge distinct « Calculé par le site » (motif quadrillé, différent de tracé, approché, non publié). Sinon il est retiré de l'affichage et, côté données, mis à `null` avec son motif. Sommes et écarts entre chiffres publiés : gardés avec le badge. | `web/tests/calcule.test.ts` ; `fonction_publique.test.ts`, `education_recherche.test.ts`, `outremer.test.ts` ; `tests/test_pouvoirs_publics.py`, `tests/test_douanes_accises.py` |

Le lexique (termes interdits, raisons, exceptions, définition admise de « niche ») est dans `docs/lexique_neutre.json`, partagé par le test du site (`web/tests/ecrans.test.ts`) et le test des données (`tests/test_neutralite.py`, sur les textes rédigés par le pipeline : avertissements, limites, lectures, définitions, règles, méthodes, périmètres, notes, tendances, règles d'ordre).

Exceptions admises (libellés officiels repris tels quels) : titres de publications (« Un capitalisme sous perfusion », « Entreprises et « niches » fiscales et sociales ») et intitulé du programme 185 « Diplomatie culturelle et d'influence ».

## Libellés corrigés côté pipeline (17/11/2026)

| Fichier | Avant | Après | Module |
|---------|-------|-------|--------|
| `realisations/*.json`, `tendance.valeur` ; `realisations/index.json`, `tendances` | « en progrès », « en recul » | « dans le sens souhaité publié », « à l’inverse du sens souhaité publié » (schéma et contrat mis à jour ; la traduction côté site est retirée) | `realisations.py` |
| `controle/aides_entreprises.json`, `publication` | renvois « idem, … » et périmètres collés au titre | titre réel dans `publication`, périmètre retenu dans le nouveau champ `variante` (le schéma refuse « idem ») | `controle.py` |
| `controle/aides_entreprises.json`, estimation CPO | `annee_donnees: null` sans explication ; périmètre « …, niches sociales » | nouveau champ `annee_donnees_note` (obligatoire si l'année manque) ; « exonérations de cotisations (souvent appelées niches sociales) » | `controle.py` |
| `prelevements/tva_conso.json`, `methode` | « ces taxes pèsent sur les revenus » | « ces taxes sont imputées aux revenus » | `prelevements.py` |
| `vie_politique/partis/*.json` | ordre implicite, départage dépendant de la forme du nom | champ `ordre` (aide totale décroissante, puis `nom_tri`) ; nouveau champ `nom_tri` (capitales sans accents, article initial retiré) ; `nom` reste la dénomination publiée | `vie_politique.py` |
| `vie_politique/candidats/*.json` | ordre du fichier source | champ `ordre` (circonscription puis nom, alphabétique) et liste triée ; `collecte_le` lu dans les manifestes de collecte (une reproduction sans téléchargement ne change plus la date) | `vie_politique.py` |
| `local/decisions/index.json`, `limites` | « reste tres partielle » | « Listes publiées et collectées : 32 communes sur 34 875, 14 intercommunalités sur 1 255, 15 départements sur 101, 8 régions sur 18 » (calculé à chaque production) | `local.py` |
| `niches/sociales.json`, `avertissement` | « Les niches sociales sont l'équivalent… » | « Les exonérations de cotisations (souvent appelées niches sociales) sont l'équivalent… » | `niches.py` |

## Journal des corrections (17/11/2026)

| Type | Avant | Après | Raison |
|------|-------|-------|--------|
| Cadrage | « Où va l'argent que tu paies ? » (accueil, titre du document, Open Graph, Twitter, image de partage) | « Où va l'argent que tu verses ? » | Règle 3 : « paies » cadre en perte, « finances » en gain. |
| Cadrage | « Ton téléphone calcule ce que tu paies » | « … ce que tu verses » | Règle 3. |
| Cadrage | « Ce que tu finances chaque année », « Ce que tu finances en un an », bouton « Ce que tu finances », titre de route | « Ce que tu verses … » | Règle 3. |
| Cadrage | Saisie : « le site calcule ce que tu finances » | « … ce que tu verses » | Règle 3. |
| Cadrage | État : « Et ce que tu finances ? » ; « Le reste finance la Sécurité sociale » | « Et ce que tu verses ? » ; « Le reste va à la Sécurité sociale et aux collectivités » | Règle 3. |
| Cadrage | Carte de partage : « Ce que je finance en un an » | « Ce que je verse en un an » | Règle 3. |
| Lexique | Dépenses fiscales : « Elle n'est pas versée, mais elle coûte comme une dépense » | « Elle n'est pas versée : elle diminue les recettes publiques. L'administration en publie une estimation, mesure par mesure. » | Règle 2 (« coûte » cadre en perte). |
| Lexique | « Les mesures les plus coûteuses en 2025 (estimation) » | « Les mesures au montant estimé le plus élevé en 2025 » | Règle 2. |
| Lexique | Contrôle : « qui cherche à peser sur les décisions » | « quelles organisations déclarent des actions de représentation d'intérêts auprès des décideurs publics » | Règle 9 (insinuation). |
| Lexique | « Contrôle, influence et aides aux entreprises » (titre, route, page vide) | « Contrôle, représentation d'intérêts et aides aux entreprises » | Règle 9 : terme de la HATVP. |
| Lexique | « Ministères les plus visés par des actions déclarées » | « Ministères les plus souvent désignés comme destinataires d'actions déclarées, par nombre d'actions » | Règle 9. |
| Lexique | Contrôle : « combien les entreprises reçoivent selon les études publiées » | « ce que les études publiées comptent comme aides aux entreprises » | Le montant dépend du périmètre de chaque étude. |
| Lexique | Dette : « ce que coûtent les intérêts chaque année » | « le montant des intérêts payés chaque année » + « Les montants sont aussi donnés en part du PIB » | Règle 2 ; dette remise en contexte. |
| Lexique | Vie politique : « Ce que l'État dépense pour la démocratie » | « … au titre de la vie politique » | Formule laudative. |
| Lexique | Calcul : « variante Insee où ces taxes pèsent sur les revenus » ; « certaines règles pèsent davantage » | « … sont imputées aux revenus » ; « … comptent davantage » | Règle 2. |
| Niche | « Dépenses fiscales et niches sociales » (titre, route), menu « Niches fiscales » | « Dépenses fiscales et exonérations de cotisations », menu « Dépenses fiscales », définition « (souvent appelée niche fiscale) » | Règle 4. |
| Niche | « Niches sociales » | « Exonérations de cotisations sociales (souvent appelées niches sociales) » | Règle 4. |
| Couleur | Tendance « en progrès » en vert, « en recul » en rouge (couleur d'erreur) | couleur du texte, en gras, pour les deux | Règle 7. |
| Couleur | Réductions d'impôt en vert | couleur du texte, signe « − » conservé | Règle 7. |
| Libellé | Tendances « en progrès » / « en recul » | « dans le sens souhaité publié » / « à l'inverse du sens souhaité publié » | La tendance est relative au sens publié par l'administration. |
| Ordre | Partis dans l'ordre du fichier source | aide totale décroissante, puis alphabétique, règle écrite sous le tableau | Règle 6. |
| Ordre | Candidats dans l'ordre du fichier source | circonscription puis nom, règle écrite sous le tableau | Règle 6. |
| Ordre | Amendements adoptés : ordre implicite | date décroissante, règle écrite | Règle 6 (auteurs et groupes cités). |
| Sélection | « Qui reçoit l'argent » : organismes seulement | renvoi aux prestations aux personnes (Sécurité sociale) | Règle 8. |
| Sélection | Aides aux entreprises sans contrepoint | renvoi aux sommes versées aux ménages, même format | Règle 8. |
| Sélection | UE : solde net sans ses limites | limites publiées affichées sous le tableau (marché unique, rubriques partielles) | Le solde comptable seul suggère une conclusion. |
| Citation | Titres de publications sans marque ; « (données null) » | titres entre guillemets, mention d'année masquée si absente | Distinguer le titre d'un auteur et le texte du site. |
| Non publié | « 31 € n'ont pas de destinataire publié. » | « … publié en données ouvertes : cela décrit l'état de la publication, pas l'usage de l'argent. » | Règle 9. |
| Non publié | Traçabilité : part non publiée sans précision | « elle ne dit rien de la régularité ni de l'utilité de la dépense » | Règle 9. |
| Charte | (absent) | Démarche : « Le site ne soutient aucun parti, aucun candidat ni aucune position sur le niveau des impôts ou des dépenses. » ; règles « Chaque sujet est présenté avec les mêmes formats : montant, source, part tracée, écarts. » et « Partis et candidats : même tableau pour tous, dans un ordre neutre affiché sous chaque liste. » | Règles 1, 5, 6. |

## Règle « chiffre calculé par le site » (décision du 18/11/2026)

Un chiffre que le site calcule lui-même à partir de montants publiés n'est affiché que si :

1. tous ses montants portent sur la même année ;
2. ils portent sur le même périmètre ;
3. la méthode est écrite à côté du chiffre ;
4. il porte le badge « Calculé par le site » (`badgeCalcule(methode)` dans `web/src/util.ts`, qui refuse une méthode vide).

Sinon le chiffre est retiré de l'affichage, et de préférence mis à `null` avec son motif dans les données. Application au 18/11/2026 :

| Chiffre | Décision |
|---------|----------|
| Montant par étudiant (éducation et recherche, 457 €) | retiré : dépenses d'une année civile, étudiants d'une année universitaire ; données : `cout_par_etudiant_eur` à `null`, motif dans `mention` |
| Coût complet moyen par emploi (fonction publique, 78 358 € ; page programme) | affiché seulement si emplois et dépenses de personnel sont de la même année ; aujourd'hui emplois LFI 2023 et dépenses 2024 : retiré ; données : `cout_moyen_par_etpt_eur` à `null`, motif dans `motif_cout_moyen` |
| Montant par habitant outre-mer (crédits 2024 divisés par la population) | retiré : année de la population non publiée avec elle |
| Montant par journée de détention (justice), reste à charge des départements (solidarités) | non affichés |
| Indemnités des membres du Gouvernement calculées depuis les décrets | gardées : statut « calculé par le site » et formule |
| Indemnité des sénateurs reprise de celle des députés | non publiée (`null`) tant qu'aucune source du Sénat ne l'écrit |
| Destination 2025 des recettes douanières attribuée par déduction | non publiée (`parts` vide, `statut` = `non_publie`) |
| Sommes et écarts entre chiffres publiés (facilité pour la reprise, cofinancement national, écarts entre sources, payé dans l'année par différence de cumuls, part des charges de personnel, médiane des prix) | gardés avec le badge et la méthode |

Parts « sur 100 € » (décision du 18/11/2026) : ce sont des parts de chiffres publiés par une même source, sans badge ; une part qui combine deux sources porte le badge « Calculé par le site » et sa méthode (exemple : part des charges de personnel des hôpitaux). La part personnelle (« ce que tu verses ») relève du calcul personnel, décrit sur la page Méthode.

## Personnes nommées (décision du propriétaire, 18-19/11/2026)

Seules des personnes publiques agissant dans leur mandat ou leur candidature sont nommées, à partir de sources officielles :

- candidats : comptes de campagne (CNCCFP, Journal officiel) ;
- parlementaires : réserve parlementaire (décision « On nomme »), auteurs d'amendements et de motions, votes publiés (décision « On nomme aussi » du 19/11/2026) ;
- membres du Gouvernement : barèmes par fonction seulement, jamais par nom.

Tous sont présentés de la même façon (même tableau, ordre neutre écrit, aucune mise en avant). Aucune autre personne physique n'est nommée : bénéficiaires, agents, particuliers cités dans des actes restent agrégés ou retirés.

## Personnes nommées (décision du 19/11/2026)

Les parlementaires sont nommés comme auteurs d'amendements fiscaux et par leur vote nominatif publié aux scrutins publics (écran « Qui a voté tes impôts », `/decisions/qui-a-vote`, contrat 2.70). Seuls le nom, le groupe politique, la circonscription, le vote et l'amendement sont publiés : ni date de naissance, ni adresse, ni profession, ni patrimoine, ni déclaration à la HATVP, ni photo. Même traitement pour tous les groupes : aucun classement, score, palmarès ni qualificatif ; groupes dans l'ordre alphabétique, règle écrite à l'écran ; décomptes tels que publiés. Avertissements toujours affichés : un non-votant n'est pas forcément absent, délégations de vote, mises au point, un vote sur un article n'est pas un vote sur l'impôt entier. Un parlementaire qui a été candidat à une élection nationale (présidentielle, tête de liste européenne) est nommé comme les autres, comme auteur d'amendement et par son vote nominatif, sur cet écran et dans le bloc décisions (décision du 19/11/2026, qui lève le masquage de la règle de 2.11) ; rien d'autre n'est publié sur lui (ni donateurs, ni mandataires, ni adresse, ni date de naissance, ni déclaration à la HATVP), et le détail par candidat des comptes de campagne reste dans le seul bloc vie politique. Tests : `tests/test_qui_a_vote.py`, `web/tests/qui_a_vote.test.ts`.
