# Règles des agents de renfort « Où vont mes impôts » (vague 3, sessions distantes)

À lire en entier avant d'agir. Elles s'imposent à toi.

## Projet
Dépôt public MoonEyes/Ou-vont-mes-impots. Site citoyen gratuit, non officiel, STRICTEMENT neutre : à partir d'un salaire, ce que la personne verse et où va chaque euro (open data). Site web (pas une application) : Vite + TypeScript sans framework, vitest + happy-dom, prérendu de toutes les routes. Pipelines Python (un module par axe dans pipeline/, orchestrés par pipeline/tout.py), contrat d'interface docs/contrat_interface.md, schémas docs/schemas/, validateur docs/valider_contrat.py.
À lire selon ta mission : README.md, docs/contrat_interface.md, docs/NEUTRALITE.md, docs/lexique_neutre.json, pipeline/reproductible.py, pipeline/sirene.py, collecte/collecte.py, tests/test_confidentialite.py, tests/test_neutralite.py, un pipeline récent comme modèle (pipeline/prestations.py ou pipeline/europe_comparaison.py), et pour le site web/src/routes.ts, web/src/donnees.ts, web/src/util.ts, web/src/composants/, web/tests/aide-dom.ts, web/tests/ecrans.test.ts.

## Ton dossier de travail
Ton coordinateur t'a donné un dossier à toi (une copie de travail git sur ta branche agent/<nom>, partie de base/vague3). Tu n'écris QUE dedans (et dans /tmp). D'autres agents travaillent en même temps dans d'autres dossiers sur la même machine.
Les missions ont été écrites pour un ancien mode « arbre partagé » : quand une mission dit « par script sous flock », « /tmp/ovmi-web.lock » ou « /tmp/ovmi-partage.lock », ignore le verrou : dans TON dossier, édite directement le fichier partagé, mais en AJOUT seulement (aucune ligne existante modifiée, déplacée ni reformatée), pour que la fusion avec le travail des autres soit simple. Quand une mission cite /home/claude/outils/lourd.sh, utilise coordination/lourd.sh (même usage). Quand elle dit « un autre agent » possède un fichier, ne modifie ce fichier que par l'ajout d'une ligne.

## Ressources machine
- Commandes lourdes (pytest, valider_contrat, tsc, vitest, npm, gros traitements) : `<dossier coordination>/coordination/lourd.sh <commande>` (créneaux = nombre de cœurs). Timeout 600000 ms ou arrière-plan.
- Disque : au plus 500 Mo de bruts dans data/lake/<axe>/ de ton dossier ; sous 5 Go libres (`df -h ~`), ne télécharge plus et signale-le. Supprime tes temporaires.
- Mémoire : lecture en flux, jamais plus de 1,5 Go en mémoire.
- web/node_modules : ton coordinateur l'a relié à une installation commune (lien symbolique). Ne lance pas npm install/ci dans ton dossier ; s'il manque, signale-le.

## Fichiers et périmètre
- Données : tes fichiers sont pipeline/<axe>.py, tests/test_<axe>.py, docs/schemas/<axe>_*.schema.json, site/data/<axe>/. En ajout seulement : docs/contrat_interface.md (ta section à la fin de la partie 2, prochain numéro libre, sans changer la version), docs/valider_contrat.py (tes lignes dans FICHIERS), collecte/catalogue.json (tes entrées), pipeline/tout.py (ton étape via le helper axe(), avant le datapackage), pipeline/entrees_lac.json. Ne régénère PAS docs/datapackage.
- Site : ton écran web/src/ecrans/<ecran>.ts, ton test web/tests/<ecran>.test.ts, tes fixtures web/tests/fixtures/<sous-dossier à toi>. Une route = UNE ligne ajoutée dans ROUTES (web/src/routes.ts), à la fin du groupe de ton parent, avec parent, voisins, famille et picto existants. CSS : réutilise ; sinon un bloc à la FIN de styles.css préfixé `/* <écran> */`. N'édite pas web/tests/ecrans.test.ts.
- Jamais : .github/ (sauf exception écrite dans ta mission), deploy/, fichiers d'un autre axe.

## Contenu
- Confidentialité : aucune personne physique nommée. Un bénéficiaire n'est nommé que si sirene.personne_morale(catégorie juridique) est vrai ; sinon agrégé. Politique agricole commune : aucun bénéficiaire individuel, même personne morale. Colonnes adresse, courriel, téléphone, dirigeant, responsable, nom, prénom : supprimées à la lecture. Textes libres passés par local.objet_publiable. Valeurs « nc », secret statistique, vides : null avec mention, jamais 0. Pas de déclaration de patrimoine ou d'intérêts de la HATVP.
- Neutralité : libellés factuels, lexique partagé, aucune couleur ni classement de valeur, aucun mot de jugement ; chaque estimation avec producteur, périmètre, méthode ; écarts entre sources montrés, jamais tranchés ni additionnés. Vocabulaire « ce que tu verses » ; tutoiement ; jamais de sigle seul pour le public ; pas de tiret long (—).
- Design en place « billet découpé » (encre #1E1548, lavande #F3F0FF, familles de couleurs fixes, Bricolage Grotesque et Figtree, contour 2,5 px, motifs : plein = tracé, pointillé = approché, hachuré = non publié) : réutilise composants et classes, n'invente pas de direction visuelle. Mobile d'abord (390 px) puis 1440 px, accessible (titres hiérarchisés, tableaux avec caption et th scope, focus visible, rien que la couleur pour porter un sens), aucune requête externe.
- Technique : dates via pipeline/reproductible.py ; sorties reproductibles octet pour octet (pas de hash(), pas d'itération sur set, pas de date du jour) ; chaque fichier porte millesime et source (URL) ; < 5 Mo par fichier, < 1 Mo pour ce que le navigateur charge ; bruts hors git dans data/lake/. Ne contourne jamais un 403, 429 ou anti-robot : note la source comme inaccessible. 2 à 5 reprises espacées si le réseau flanche.
- Règle n°0 : cherche d'abord l'existant (jeux officiels, dépôts publics) ; classe chaque trouvaille réutilisable tel quel / à adapter / inspiration, avec licence et date du dernier commit.

## Vérification
- Données : `lourd.sh python3 -m pytest -q` (suite complète, dans ton dossier) et `lourd.sh python3 docs/valider_contrat.py --strict` (0 non conforme, 0 orphelin). Un échec de tests/test_reproductibilite.py dû à l'absence de bruts n'est pas de ton fait : signale-le.
- Site : `lourd.sh bash -c 'cd web && npx tsc --noEmit -p . && npx vitest run tests/<ton_fichier>.test.ts'`. Pas de build complet sauf si ta mission l'autorise.
- Après ton push, GitHub Actions lance « Verification » sur ta branche (tests complets données et site, build) : `gh run list --branch agent/<nom> -L 1` puis `gh run watch <id> --exit-status`. Corrige ce qui relève de toi.

## Git
Dans ton dossier : `git add <tes chemins>` puis `git commit`. Identité : `git -c user.name=MoonEyes -c user.email=14891700+MoonEyes@users.noreply.github.com commit ...`. Message terminé par :
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FZUzhVwdPgnnpM7RuuDMy1
Puis `git push -u origin agent/<nom>`. Jamais de push sur main ni sur une autre branche, jamais de force push. Si le push est refusé, donne la commande et l'erreur exactes dans ton rapport.

## Rapport final (8 lignes max, français, sans tiret long)
Branche et hash, ce qui marche maintenant (route ou fichiers), chiffres clés avec année et source, ce qui est agrégé ou masqué pour la confidentialité, sources inaccessibles, points douteux à arbitrer, résultat des vérifications (dont GitHub Actions), verdict Règle n°0.
