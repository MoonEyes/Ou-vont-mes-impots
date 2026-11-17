# Tests

Deux familles de tests, toutes sans réseau :

- `tests/test_*.py` et `collecte/tests/` : contrôles des fichiers publiés (`site/data/`) et du collecteur ;
- `tests/test_unitaires_<module>.py` : tests unitaires des fonctions de calcul des pipelines, sur de petites
  entrées construites à la main. Ils ne lisent ni `data/lake/` ni `site/data/` et tournent même sur un entrepôt
  purgé (lecture de fichiers et appels HTTP remplacés par `monkeypatch`).

Fonctions couvertes par les tests unitaires : lecture des montants (virgule décimale, espaces de milliers
insécables, « nc », « ε », « - », signe typographique), arrondis, rapprochement SIREN (`sirene`, `operateurs.choisir`),
filtres de confidentialité (`sirene.personne_morale`, `beneficiaires.statut`, `local.contient_nom_de_personne`,
`local.objet_publiable`, `controle.texte_sans_personne`), conversion F CFP vers euros, TVA théorique, répartitions
(`tracabilite.calculer_feuille`, `tracabilite.synthese`, `beneficiaires.top_et_autres`), sélection du millésime
(`niches.edition_reference`, `local.annees_ofgl`, `local.serie`, `reproductible.date_sources`).

Un test marqué `xfail(strict=True)` documente un bogue connu du pipeline, non corrigé : il passera au vert (et fera
échouer la suite, ce qui oblige à retirer la marque) le jour où le bogue sera corrigé.

## Lancer

```bash
pytest -q tests collecte/tests                       # suite complète
pytest -q tests/test_unitaires_*.py                  # tests unitaires seuls (quelques secondes)
```

## Mesurer la couverture

```bash
pip install coverage
python -m coverage run --source=pipeline,collecte --omit='*/tests/*' -m pytest -q tests collecte/tests
python -m coverage report                            # par module
python -m coverage html                              # détail ligne à ligne dans htmlcov/
```

Les scripts lancés en sous-processus (`subprocess`) par certains tests ne sont pas mesurés ; les fonctions
`produire()` qui lisent l'entrepôt restent donc peu couvertes tant que `data/lake/` est vide.

<!--
Mesure du 17/11/2026, entrepôt data/lake purgé, suite complète (pytest tests collecte/tests).
Avant : 966 tests, couverture totale 31 %. Après : 1197 tests dont 2 xfail (bogues connus), 34 %
(dénominateur modifié entre les deux mesures par l'arrivée de datapackage.py, local_fonctions.py et des tests de
prestations, développés en parallèle).

Module               avant   après
sirene.py             32 %    93 %
reproductible.py      36 %    91 %
tracabilite.py        39 %    68 %
prelevements.py       26 %    32 %
decisions.py          37 %    39 %
realisations.py       21 %    25 %
local.py              21 %    23 %
niches.py             26 %    28 %
beneficiaires.py      15 %    20 %
vie_politique.py      15 %    21 %
controle.py           33 %    34 %
operateurs.py         17 %    17 %
fetch.py              20 %    26 %
transform.py          97 %    97 %

Bogues connus (xfail strict) :
- vie_politique._deux_nombres : ["470","371","470","372"] donne (470371470, 372) au lieu de (470371, 470372).
- local.contient_nom_de_personne : « Aide à Marie de Kergariou » n'est pas reconnu (particule dans MOTS_OUTILS).

Échec préexistant, hors périmètre des tests unitaires : tests/test_reproductibilite.py::
test_produire_deux_fois_donne_les_memes_octets (secu.py produire exige des PDF absents de l'entrepôt purgé).
-->
