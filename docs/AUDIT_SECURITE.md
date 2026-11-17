# Audit sécurité, confidentialité et conformité avant mise en ligne

Date : 17/11/2026. Relecture indépendante du dépôt `MoonEyes/Ou-vont-mes-impots` (30 commits, HEAD `e961e69`, plus l'arbre de travail non commité à cette date).

## En tête : historique git

**Aucun secret ni donnée personnelle non autorisée dans l'historique git.** Rien à réécrire.

- gitleaks 8.21.2 sur les 30 commits (`gitleaks git .`) : 0 fuite. `gitleaks dir` sur `deploy/`, `collecte/`, `.github/`, `docs/`, `pipeline/`, `tests/`, `site/`, `web/src/` : 0 fuite.
- Recherche manuelle dans `git log -p --all` (61 Mo) : aucune adresse e-mail hors `noreply` (auteur `14891700+MoonEyes@users.noreply.github.com`, bot `41898282+github-actions[bot]@…`), aucun chemin local (`/home/…`, `/Users/…`, `C:\Users\…`, OneDrive), aucune adresse IP, aucun nom de bucket ni identifiant S3 renseigné (`env.exemple` : valeurs vides), aucun `GITHUB_TOKEN=` renseigné.
- Données nominatives : l'historique de `site/data/` ne contient que des personnes morales de catégorie 3xxx à 9xxx, des élus (amendements, scrutins) et des candidats (comptes CNCCFP). Les catégories 1000, 2110, 2210, 2310 n'apparaissent que dans des tests à valeurs fictives.

Le constat critique C1 porte sur des fichiers **non encore commités** (`site/data/local/`) : il faut le corriger avant leur premier commit.

## Synthèse

16 constats : 1 critique (non corrigé, correctif proposé), 5 importants (I5 corrigé en partie), 10 mineurs (M1 à M4 corrigés dans ce commit).

---

## Critique

### C1. Des personnes physiques sont nommées via les catégories juridiques 2110, 2210, 2310

`sirene.personne_morale()` traite toute catégorie 2xxx comme une personne morale. Or le groupe 2 de la nomenclature Insee regroupe les **groupements de droit privé sans personnalité morale**, dont trois sont composés de personnes physiques : 2110 indivision entre personnes physiques, 2210 société créée de fait entre personnes physiques, 2310 société en participation entre personnes physiques (et 2385, société en participation de professions libérales). Leur dénomination est très souvent le nom et le prénom des personnes.

Preuves :
- `pipeline/sirene.py:32-34` : `return bool(cj) and bool(CJ_RE.match(str(cj))) and str(cj)[0] in "23456789"`
- `pipeline/local.py:1000-1011` : seules les lignes `not sirene.personne_morale(c)` sont agrégées, le reste est publié avec `denomination`.
- `pipeline/beneficiaires.py:325-328` : même règle (aucune ligne 2xxx dans les fichiers commités aujourd'hui, mais rien ne l'empêche).
- 49 lignes (catégories 2110, 2210, 2310) dans `site/data/local/decisions/` (non commité ; le test proposé en I3 les détecte), par exemple :
  - `site/data/local/decisions/233500016/2022.json` : `900225657`, `2110`, `INDIVISION M ET MME FOUERE HENRI ET SUZANNE`
  - `site/data/local/decisions/200052264/2024.json` : `352690465`, `2210`, `PARMENTIER JEAN CLAUDE DOMINIQUE DENIS` (5 lignes 2021 à 2024)
  - `site/data/local/decisions/200053403/2016.json` : `539150292`, `2210`, `SIMON PASCAL & JOEL & JEAMS`
  - `site/data/local/decisions/233500016/2019.json` : `INDIVISION JOUSSEAUME DE LA BRETESCHE`, `INDIVISION FAUGERE RECIPON`, etc.
- La page Méthode affirme le contraire : `web/src/ecrans/methode.ts:126` « Le site nomme uniquement des personnes morales ».

Correction proposée (à appliquer par le responsable de `pipeline/`, puis régénérer `site/data/local` avant tout commit) :

```diff
--- a/pipeline/sirene.py
+++ b/pipeline/sirene.py
@@
 SIREN_RE = re.compile(r"^\d{9}$")
 CJ_RE = re.compile(r"^\d{4}$")
+# Groupements sans personnalite morale composes de personnes physiques : la denomination est
+# souvent le nom des personnes (« INDIVISION DUPONT », « DUPONT JEAN PIERRE »). Jamais nommes.
+CJ_PERSONNES_PHYSIQUES = frozenset({"2110", "2210", "2310", "2385"})
 
 
 def siren_valide(s) -> bool:
     return bool(s) and bool(SIREN_RE.match(str(s)))
 
 
+def personne_physique(cj) -> bool:
+    """1xxx (entrepreneur individuel) et groupements de personnes physiques (2110, 2210, 2310, 2385)."""
+    cj = str(cj or "")
+    return cj.startswith("1") or cj in CJ_PERSONNES_PHYSIQUES
+
+
 def personne_morale(cj) -> bool:
-    """Categories juridiques 2xxx a 9xxx (1000 = entrepreneur individuel, 0/vide = inconnu)."""
-    return bool(cj) and bool(CJ_RE.match(str(cj))) and str(cj)[0] in "23456789"
+    """Categories 2xxx a 9xxx, hors groupements de personnes physiques (voir personne_physique)."""
+    return (bool(cj) and bool(CJ_RE.match(str(cj))) and str(cj)[0] in "23456789"
+            and not personne_physique(cj))
--- a/pipeline/local.py
+++ b/pipeline/local.py
@@ def decisions(...)
-                if r.get("pp_source") or c.startswith("1"):
+                if r.get("pp_source") or sirene.personne_physique(c):
                     exclus["dont_personnes_physiques_eur"] += r["montant"]
--- a/pipeline/beneficiaires.py
+++ b/pipeline/beneficiaires.py
@@ def statut(...)
     if sirene.personne_morale(cj):
         return "pm", cj
-    if cj.startswith("1"):
+    if sirene.personne_physique(cj):
         return "pp", cj
```

Et dans `web/src/ecrans/methode.ts:126` (ainsi que la règle `regle_personnes_physiques` de `site/data/beneficiaires/index.json`) : « personnes morales et groupements (catégories juridiques 3xxx à 9xxx et 2xxx hors indivisions, sociétés créées de fait et sociétés en participation entre personnes physiques) ». Un test de non-régression est proposé en I3.

---

## Important

### I1. Les intitulés de projets des dotations ne passent pas par le filtre de noms

`objet_publiable()` (civilités, prénoms) est appliqué aux objets des subventions, pas aux intitulés des dotations d'investissement (DSIL, DETR…).

Preuves : `pipeline/local.py:642` (`propre(r.get("intitule"))[:160]` sans filtre) ; `site/data/local/dotations/epci.json` contient « …attendre confirmation M. OYARZABAL de prise en compte suite echange reunion le », et d'autres intitulés avec civilité dans `site/data/local/dotations/communes/*.json` (plusieurs dizaines d'intitulés avec « M. » ou « Mme », dont beaucoup de noms de rues ou d'enseignes).

Correction proposée :

```diff
--- a/pipeline/local.py
+++ b/pipeline/local.py
@@ def investissement_etat()
-            x["projets"].append([propre(r.get("dispositif")), propre(r.get("intitule"))[:160], round(v),
+            x["projets"].append([propre(r.get("dispositif")), objet_publiable(r.get("intitule")), round(v),
```

(`objet_publiable` renvoie `None` si un nom est détecté ; l'écran doit afficher « intitulé non publié » dans ce cas. Faux positifs acceptables : « rue Mme Fieyre » sera masqué.)

### I2. Le job qui détient `contents: write` exécute des dépendances non figées sur des données externes

**Statut : corrigé le 17/11/2026.** `data.yml` a désormais deux jobs : `produire` (`contents: read`, `persist-credentials: false`, dépendances installées par `pip install --require-hashes -r requirements.lock`) exécute le pipeline, valide puis livre un correctif de données en artifact ; `publier` (`contents: write`) n'exécute aucun code du pipeline, refuse un correctif qui touche autre chose que `data/raw/`, `data/processed/`, `site/data/`, `docs/datapackage/` (ou contient un lien symbolique), puis committe et pousse. L'issue d'échec est ouverte par un troisième job (`issues: write` seul). Actions épinglées par SHA.

`data.yml` installe `requirements.txt` (bornes larges, sans empreintes : `requirements.txt:1-9`, `pytest>=8`, `pandas>=2`…), télécharge et parse des fichiers publics, puis pousse sur `main` avec le jeton conservé par `actions/checkout` dans `.git/config` (`.github/workflows/data.yml:40`, `:48`, `:93-118`). Une dépendance compromise ou une faille d'analyse de fichier suffit à pousser du code sur `main`, donc sur le site (le workflow Pages republie après lui).

Correction proposée : séparer production et publication.

```diff
--- a/.github/workflows/data.yml
+++ b/.github/workflows/data.yml
 jobs:
-  update:
+  produire:
     permissions:
-      contents: write
-      issues: write
+      contents: read
     steps:
       - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
+        with:
+          persist-credentials: false
       ...
-      - name: Committer si les donnees ont change
-        ...
+      - run: git diff --binary -- data site/data > donnees.patch
+      - uses: actions/upload-artifact@<sha> # v4
+        with: { name: donnees, path: donnees.patch }
+  publier:
+    needs: produire
+    permissions:
+      contents: write
+    steps:
+      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
+      - uses: actions/download-artifact@<sha> # v4
+      - run: git apply donnees.patch && (garde-fou I3) && git add data site/data && git commit … && git push
+  alerter:
+    needs: [produire, publier]
+    if: failure()
+    permissions:
+      issues: write
```

Et figer les dépendances Python avec empreintes : `pip-compile --generate-hashes requirements.in -o requirements.txt`, puis `pip install --require-hashes -r requirements.txt`.

### I3. Aucun garde-fou automatique avant publication des données nominatives

Le commit automatique ajoute tout `data/` et `site/data/` (`.github/workflows/data.yml:93`) et Pages publie tout `site/data/` (`web/scripts/copier-donnees.mjs:19`). Les règles « personnes physiques » ne sont vérifiées que module par module ; C1 montre qu'une erreur de règle passe sans alerte.

Correction proposée : un test transversal exécuté par `pytest` (donc avant le commit dans `data.yml` et avant la publication dans `pages.yml`).

```python
# tests/test_confidentialite.py
"""Aucune donnee de personne physique hors elus et candidats dans site/data."""
import json
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site" / "data"
CJ_INTERDITES = re.compile(r"^(1\d{3}|2110|2210|2310|2385)$")
CLES_INTERDITES = {"donateur", "donateurs", "mandataire", "mandataire_financier", "adresse",
                   "date_naissance", "naissance", "courriel", "email", "telephone", "iban"}


def _parcourir(x, colonnes=None):
    if isinstance(x, dict):
        yield from ((k, v) for k, v in x.items())
        for v in x.values():
            yield from _parcourir(v, x.get("colonnes"))
    elif isinstance(x, list):
        if colonnes and "categorie_juridique" in colonnes and len(x) == len(colonnes) \
                and not any(isinstance(v, (list, dict)) for v in x):
            yield "categorie_juridique", x[colonnes.index("categorie_juridique")]
        for v in x:
            yield from _parcourir(v, colonnes)


def test_aucune_personne_physique_publiee():
    fautes = []
    for f in SITE.rglob("*.json"):
        for cle, val in _parcourir(json.loads(f.read_text(encoding="utf-8"))):
            if cle in CLES_INTERDITES or (cle == "categorie_juridique" and CJ_INTERDITES.match(str(val or ""))):
                fautes.append(f"{f.relative_to(SITE)} : {cle}={str(val)[:40]}")
    assert not fautes, "\n".join(fautes[:20])


def test_rien_de_restreint_dans_site():
    assert not [p for p in SITE.rglob("*") if "_restreint" in p.parts]
```

### I4. Informations RGPD absentes pour les personnes nommées (élus, candidats)

Le site republie des données personnelles issues de données publiques (comptes de campagne CNCCFP au JO, amendements et scrutins de l'Assemblée et du Sénat). La réutilisation de données personnelles publiques reste soumise au RGPD (CRPA art. L. 322-2) et l'information des personnes concernées relève de l'article 14 RGPD. La page `web/src/ecrans/mentions.ts` ne traite que des visiteurs.

Manque objectivement, sans inventer d'identité d'éditeur :
1. **Responsable du traitement et moyen de contact** : le seul contact est un ticket **public** (`web/src/ecrans/mentions.ts:8`). Une personne qui veut s'opposer doit pouvoir le faire sans exposer sa demande ni créer de compte GitHub : ajouter un canal privé (adresse électronique dédiée, ou formulaire « Report a vulnerability / Private advisory » activé sur le dépôt). L'anonymat LCEN de l'éditeur non professionnel ne dispense pas de ce canal.
2. **Finalités et base légale** : information du public sur l'usage de l'argent public ; base proposée à faire valider : intérêt légitime (art. 6.1.f).
3. **Catégories de données et personnes** : candidats (nom, nuance, circonscription, montants du compte, décision CNCCFP) ; élus (nom, groupe, amendements, votes).
4. **Sources** : JO et CNCCFP, open data AN et Sénat, avec dates de collecte (déjà en partie dans « Sources et mises à jour »).
5. **Durée de conservation** : non indiquée (comptes 2012 à 2024 publiés sans limite). À fixer et écrire (par exemple : tant que la source officielle les publie).
6. **Droits** : accès, rectification, effacement, limitation, **opposition (art. 21)**, et réclamation auprès de la CNIL (cnil.fr).
7. **Destinataires et transferts** : hébergement GitHub Pages aux États-Unis (déjà cité pour les journaux, à mentionner aussi pour ces données).

Proposition de bloc à ajouter dans `mentions.ts` (à compléter par l'éditeur, les crochets sont des champs à remplir) :

```html
<h2>Données personnelles des élus et candidats</h2>
<p>Le site republie, à des fins d'information du public sur l'argent public, des données déjà publiées par
l'administration : nom, nuance politique, circonscription, montants et décision des comptes de campagne
(CNCCFP, Journal officiel) ; nom, groupe, amendements et votes des parlementaires (open data de l'Assemblée
nationale et du Sénat). Base légale : intérêt légitime (art. 6.1.f du RGPD). Aucune autre donnée personnelle
n'est collectée. Durée : [durée retenue]. Hébergement : GitHub Pages (États-Unis).</p>
<p>Tu peux demander l'accès, la rectification, l'effacement ou t'opposer à la publication te concernant :
[canal privé]. Réponse sous un mois. Tu peux aussi saisir la CNIL (www.cnil.fr).</p>
```

### I5. Le jeton GitHub de l'alerte est visible du processus de collecte

`deploy/env.exemple` place `OVMI_ALERTE_GITHUB_JETON` dans `/etc/ovmi/stockage.env`, chargé aussi par `ovmi-collecte.service` (`deploy/systemd/ovmi-collecte.service`, `EnvironmentFile=`), qui télécharge et analyse des fichiers non fiables.

**Corrigé partiellement dans ce commit** : `ovmi-collecte-alerte.service` lit en plus `-/etc/ovmi/alerte.env` (facultatif), `installer_vps.sh` crée ce fichier en `600 root:root`, `env.exemple` recommande d'y mettre le jeton. **Action manuelle restante sur le VPS** : relancer `installer_vps.sh` (ou créer le fichier), déplacer `OVMI_ALERTE_GITHUB*` de `stockage.env` vers `alerte.env`, puis vider ces lignes dans `stockage.env`.

---

## Mineur

### M1. Actions GitHub non épinglées par SHA, droits accordés au niveau du workflow (corrigé)

Avant : `actions/checkout@v4`, `@v7`, `setup-python@v5`, `setup-node@v7`, `configure-pages@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5` ; `pages.yml` donnait `pages: write` et `id-token: write` au job de construction qui exécute `npm ci` (code tiers).

Corrigé : chaque action épinglée sur le SHA du tag (résolu par `git ls-remote`, version exacte en commentaire) ; `permissions: {}` au niveau des deux workflows ; `construire` : `contents: read`, `pages: read`, `persist-credentials: false` ; `deployer` seul : `pages: write`, `id-token: write` ; `data.yml` : droits déclarés au niveau du job.

À ajouter (hors périmètre de ce commit, fichier `.github/dependabot.yml`) pour garder les SHA à jour :

```yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: monthly }
```

### M2. Expressions `${{ }}` dans un script shell (corrigé)

`.github/workflows/data.yml` (étape « Ouvrir une issue ») interpolait `${{ github.server_url }}`, `${{ github.repository }}`, `${{ github.run_id }}`. Valeurs non contrôlables par un tiers (pas d'injection exploitable), remplacées par `$GITHUB_SERVER_URL`, `$GITHUB_REPOSITORY`, `$GITHUB_RUN_ID` par hygiène. Aucun `pull_request_target`, aucun déclencheur `pull_request` ; `workflow_run` de `pages.yml` ne suit que `data.yml` (planifié ou manuel) et reconstruit `ref: main` : sûr tant que `data.yml` n'a pas de déclencheur `pull_request`.

### M3. L'issue d'alerte publique révélait le nom d'hôte du VPS ; masquage incomplet (corrigé)

`deploy/alerte.py` : titre `Collecte hebdomadaire en echec ({socket.gethostname()}, …)` publié sur le dépôt public (le nom d'hôte OVH identifie la machine). Retiré. Le masque des lignes de journal couvre désormais aussi `jeton`, `mot_de_passe`, `bucket`, `rclone_config` et les adresses IPv4. Tests `collecte/tests/test_stockage.py` : 24 réussis.

### M4. Service d'alerte peu confiné (corrigé)

`deploy/systemd/ovmi-collecte-alerte.service` n'avait que `ProtectSystem`, `ProtectHome`, `PrivateTmp`, et l'écriture sur `/var/lib/ovmi`. Ajouté : `ReadOnlyPaths=/var/lib/ovmi` (il ne fait que lire), `PrivateDevices`, `ProtectKernel*`, `ProtectControlGroups`, `ProtectClock`, `ProtectHostname`, `RestrictSUIDSGID`, `RestrictRealtime`, `RestrictNamespaces`, `LockPersonality`, `RestrictAddressFamilies`, `UMask=0077`, `TimeoutStartSec=5min`.

### M5. La collecte peut réécrire son propre code

`ovmi-collecte.service` : `ReadWritePaths=/var/lib/ovmi` couvre le dépôt cloné (`/var/lib/ovmi/ou-vont-mes-impots`, propriétaire `ovmi`) d'où est lancé `ExecStart`. Une faille d'analyse d'un fichier téléchargé peut donc persister en modifiant le code exécuté au prochain passage, avec les clés S3 en environnement. Correction proposée : dépôt possédé par `root` (lecture seule pour `ovmi`), entrepôt `data/lake` déplacé hors du dépôt (`OVMI_LAKE=/var/lib/ovmi/lake`, si `collecte.py` le permet, sinon lien symbolique), `ReadWritePaths=/var/lib/ovmi/lake /var/lib/ovmi/journaux /var/lib/ovmi/.cache`, et `git pull` fait par root (pas par `OVMI_MAJ_AUTO`).

### M6. Vérification de rclone et de pip

`deploy/installer_vps.sh` : `SHA256SUMS` vient du même serveur que l'archive (intégrité, pas authenticité) ; ce fichier est signé PGP par l'équipe rclone, vérifier la signature (`gpg --verify SHA256SUMS`) avec la clé publiée. `pip install` sans `--require-hashes` (voir I2).

### M7. Le test d'`env.exemple` ignore le mot « JETON »

`collecte/tests/test_stockage.py:411` ne vérifie que `SECRET`, `ACCESS_KEY`, `TOKEN`, `PASSWORD` ; la variable est `OVMI_ALERTE_GITHUB_JETON` (vide aujourd'hui).

```diff
-        if any(m in cle for m in ("SECRET", "ACCESS_KEY", "TOKEN", "PASSWORD")):
+        if any(m in cle for m in ("SECRET", "ACCESS_KEY", "TOKEN", "JETON", "PASSWORD", "MOT_DE_PASSE")):
```

### M8. En-têtes HTTP impossibles sur GitHub Pages

CSP stricte en balise `meta` (`web/index.html:6-9` : `default-src 'self'`, `script-src 'self'`, `connect-src 'self'`, `object-src 'none'`), `referrer no-referrer`, aucun script en ligne dans `dist/index.html`. Mais GitHub Pages ne permet pas d'en-têtes personnalisés : `frame-ancestors` est ignoré dans une balise `meta`, pas de `X-Frame-Options`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`. Risque faible (aucune action à effet de bord, aucune donnée stockée). Si un hébergeur avec en-têtes est retenu plus tard : `Content-Security-Policy` identique plus `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Permissions-Policy: interest-cohort=(), camera=(), microphone=(), geolocation=()`. Durcissement possible côté code : `require-trusted-types-for 'script'` imposerait de remplacer les `innerHTML` (tous échappés par `h()` aujourd'hui).

### M9. User-Agent sans moyen de contact

`collecte/collecte.py:51` et `pipeline/*.py` (`ou-vont-mes-impots/0.1 (projet citoyen open source)`, `ou-vont-mes-impots/pipeline`) : honnêtes mais sans URL. Proposé : `ou-vont-mes-impots/0.3 (+https://github.com/MoonEyes/Ou-vont-mes-impots)`. `pipeline/prelevements.py:397` lit la réponse entière en mémoire sans plafond de taille (pas de `stream`).

### M10. Prénom dans la licence

`LICENSE:3` : « Copyright (c) 2026 Benjamin » relie le pseudonyme `MoonEyes` à un prénom, alors que les mentions légales invoquent l'anonymat de l'éditeur non professionnel. Choix de l'éditeur ; « Copyright (c) 2026 les contributeurs de Où vont mes impôts » est possible (la licence MIT n'exige pas de nom civil).

Incohérence de texte associée à C1 : `web/src/ecrans/methode.ts:126` ne cite pas les parlementaires nommés dans les blocs amendements et scrutins (`site/data/decisions/index.json`, `regle_personnes`). Ajouter « les élus (députés, sénateurs) auteurs d'amendements ou votants, et le Gouvernement ».

---

## Points vérifiés conformes

- **Secrets** : voir l'en-tête ; `env.exemple` vide ; `.gitignore` exclut `data/lake/`, `data/processed/_restreint/`, `web/dist`, `web/public/data`.
- **Personnes physiques dans `site/data/`** (commité et non commité) : aucun champ donateur, mandataire, adresse, date de naissance, courriel, téléphone, IBAN ; aucune déclaration HATVP ; « PAC » n'apparaît que dans des libellés de conventions (« AVENANTS PAC - CP NOVEMBRE 2023 »), pas de bénéficiaires de la PAC ; aucune catégorie 1000 ; `beneficiaires/` : catégories 3xxx à 9xxx uniquement ; `vie_politique/` : champs CNCCFP seulement (candidat, nuance, circonscription, montants, décision) ; `decisions/` : élus, Gouvernement, commissions, et 185 noms d'élus candidats masqués ; `tracabilite/` : aucun nom de personne. `tests/` : données fictives (`"1 rue X"` dans `tests/test_contrat.py:68` sert à vérifier un rejet).
- **web/** : CSP stricte ; seule requête réseau `fetch` sur `data/…` relatif, chemin validé (`web/src/donnees.ts:17-21`) ; saisie en mémoire seulement (`web/src/etat.ts:1-2`), aucun `localStorage`, `sessionStorage`, `indexedDB`, cookie, `sendBeacon`, WebSocket ; les URL présentes dans le bundle sont des références documentaires de `modele-social`, jamais appelées ; paramètres d'URL validés (`/^\d{3}$/`) ou échappés par `h()` ; `npm audit` : 0 vulnérabilité (avec et sans dépendances de développement).
- **Pipeline et collecte** : vérification TLS par défaut partout (aucun `verify=False`, `CERT_NONE`) ; aucune URL `http://` dans `catalogue.json` et `portails_ods.json` ; aucun `eval`, `exec`, `pickle`, `marshal`, `yaml.load`, `shell=True` ; archives zip extraites membre par membre avec `_rel_sur()` (supprime `..` et chemins absolus, `collecte/conversion.py:429-432`), plafond de membres et de taille décompressée ; archives JORF lues en flux, fichiers écrits sous un nom reconstruit par expression régulière (`pipeline/decisions.py:645-648`) ; 401, 403 et 451 jamais contournés (`collecte/collecte.py:177-179`, `pipeline/vie_politique.py:79-80`, `pipeline/prelevements.py:404-405`), 429 et 5xx avec attente exponentielle et `Retry-After` (`collecte/collecte.py:180-186`) ; User-Agent explicite.
- **Mentions LCEN** (`web/src/ecrans/mentions.ts`) : éditeur non professionnel anonyme avec renvoi à l'hébergeur (art. 6, III, 2 LCEN), hébergeur identifié avec adresse, absence de cookie et de traceur déclarée et vérifiée dans le code.
