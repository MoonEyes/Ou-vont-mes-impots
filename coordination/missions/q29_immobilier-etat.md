Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent de données « immobilier-etat ») : nouvel axe pipeline/immobilier_etat.py → site/data/immobilier_etat/, avec tests/test_immobilier_etat.py, docs/schemas/immobilier_etat_*.schema.json, section du contrat, catalogue, branchement dans tout.py et entrees_lac.json (sous flock). Contenu visé : le parc immobilier de l'État (nombre de biens, surfaces, valeur, par ministère et par département, jeux de données « inventaire immobilier de l'État »), les cessions (produits par année), les loyers payés par l'État pour les biens qu'il loue (agrégés ; bailleurs nommés seulement s'ils sont des personnes morales), le compte d'affectation spéciale « Gestion du patrimoine immobilier de l'État ». Sources : data.gouv (Direction de l'immobilier de l'État), budget.gouv.

Règle n°0 : cherche d'abord les jeux officiels et les dépôts publics existants. Pas d'écran web dans ta mission (un autre agent l'affichera) : documente bien la section du contrat pour lui.

Termine par le rapport final du brief.