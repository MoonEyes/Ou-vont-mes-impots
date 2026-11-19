"""Valide les fichiers de site/data contre le contrat d'interface (docs/schemas/*.schema.json).

Usage :
    python docs/valider_contrat.py            # tous les fichiers
    python docs/valider_contrat.py --quiet    # n'affiche que les erreurs et le bilan
    python docs/valider_contrat.py --strict   # un fichier JSON couvert par aucun schema est une erreur

Controles : JSON Schema (docs/schemas/, references croisees via commun.schema.json), puis hors schema :
liens `fichier` des arbres et des index, conservation des groupes de beneficiaires (a 1 euro pres),
sommes de parts des prelevements (= 1).

Performance : chaque schema est compile une fois par processus ; les fichiers sont valides en parallele
(`--processus`, defaut : coeurs disponibles, 8 au plus), par lots tries du plus lourd au plus leger. Un fichier
deja conforme, de meme contenu, avec les memes schemas et la meme version de jsonschema, n'est pas revalide
contre son schema (cache hors depot, `OVMI_CACHE_CONTRAT` ou dossier temporaire ; `--sans-cache` pour tout
rejouer) ; les controles hors schema sont toujours rejoues. Le resultat est identique dans tous les cas.

Code de sortie : 0 si tout fichier present est conforme ; 1 si un fichier present est
non conforme ou si un fichier marque "existant" manque. Un fichier "prevu" absent est
signale (PREVU) sans faire echouer la validation ; un fichier orphelin (aucun schema) est
signale (ORPHELIN), bloquant seulement avec --strict.
"""
from __future__ import annotations

import argparse
import glob
import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SCHEMAS = Path(__file__).resolve().parent / "schemas"
EXEMPLES = Path(__file__).resolve().parent / "exemples"

# (schema, motif relatif a site/data, etat attendu). Tout fichier JSON de site/data doit etre couvert par au
# moins un motif : un fichier orphelin fait echouer la validation (contrat a completer).
FICHIERS = [
    ("meta.schema.json", "meta.json", "existant"),
    ("mise_a_jour.schema.json", "mise_a_jour.json", "existant"),   # pipeline/tout.py (contrat 2.22)
    ("sankey_etat.schema.json", "sankey_etat*.json", "existant"),
    ("nature_etat.schema.json", "nature_etat.json", "existant"),
    ("arbre_etat.schema.json", "arbre/*.json", "existant"),
    ("arbre_etat.schema.json", "arbre_lfi2025/*.json", "existant"),
    ("arbre_etat.schema.json", "arbre_plf2025_nature/*.json", "existant"),
    ("programme.schema.json", "programmes/*.json", "existant"),
    ("arbre_administrations.schema.json", "arbre_administrations/racine.json", "existant"),
    ("arbre_administrations_methode.schema.json", "arbre_administrations/methode.json", "existant"),
    ("administrations.schema.json", "administrations.json", "existant"),
    ("recettes.schema.json", "recettes.json", "existant"),
    ("cofog.schema.json", "cofog.json", "existant"),
    ("deficit.schema.json", "deficit.json", "existant"),
    ("communes.schema.json", "communes/*.json", "existant"),
    # contrat 1.1 : precision par programme (pipeline/beneficiaires.py)
    ("nature_programme.schema.json", "nature/[0-9]*.json", "existant"),
    ("effectifs.schema.json", "effectifs/[0-9]*.json", "existant"),
    ("beneficiaires_programme.schema.json", "beneficiaires/programme_*.json", "existant"),
    ("france2030.schema.json", "beneficiaires/france2030.json", "existant"),
    ("marches_etat.schema.json", "beneficiaires/marches_etat.json", "existant"),
    ("beneficiaires_index.schema.json", "beneficiaires/index.json", "existant"),
    # contrat 1.2 : realisations (pipeline/realisations.py)
    ("realisations.schema.json", "realisations/[0-9]*.json", "existant"),
    ("realisations_index.schema.json", "realisations/index.json", "existant"),
    # contrat 1.3 : vie politique (pipeline/vie_politique.py)
    ("vie_politique_annees.schema.json", "vie_politique/annees.json", "existant"),
    ("vie_politique_partis.schema.json", "vie_politique/partis/*.json", "existant"),
    ("vie_politique_scrutin.schema.json", "vie_politique/scrutins/*.json", "existant"),
    ("vie_politique_candidats.schema.json", "vie_politique/candidats/*.json", "existant"),
    # contrat 1.4 : prelevements hors bulletin et affectation (pipeline/prelevements.py)
    ("prelevements_affectation.schema.json", "prelevements/affectation.json", "existant"),
    ("prelevements_tva_conso.schema.json", "prelevements/tva_conso.json", "existant"),
    ("prelevements_taxe_fonciere.schema.json", "prelevements/taxe_fonciere.json", "existant"),
    ("prelevements_taxe_fonciere_dep.schema.json", "prelevements/taxe_fonciere/*.json", "existant"),
    # Union europeenne : contribution, retours, beneficiaires nommes (pipeline/ue.py)
    ("ue_contribution.schema.json", "ue/contribution.json", "existant"),
    ("ue_retours.schema.json", "ue/retours.json", "existant"),
    ("ue_beneficiaires_index.schema.json", "ue/beneficiaires/index.json", "existant"),
    ("ue_beneficiaires_dep.schema.json", "ue/beneficiaires/[0-9n]*.json", "existant"),
    ("affectation_prelevements.schema.json", "affectation_prelevements.json", "prevu"),
    # contrat 1.5 : Securite sociale et protection sociale (pipeline/secu.py)
    ("secu_arbre.schema.json", "secu/arbre/*.json", "existant"),
    ("secu_arbre.schema.json", "secu/arbre_2025/*.json", "existant"),
    ("secu_arbre.schema.json", "secu/cps/*.json", "existant"),
    ("secu_index.schema.json", "secu/index.json", "existant"),
    # prestations versées aux ménages : montants, bénéficiaires, départements (pipeline/prestations.py)
    ("prestations_index.schema.json", "prestations/index.json", "existant"),
    ("prestations_nationales.schema.json", "prestations/nationales.json", "existant"),
    ("prestations_departement.schema.json", "prestations/departements/*.json", "existant"),
    # subventions au format des données essentielles des conventions de subvention (pipeline/subventions.py)
    ("subventions_index.schema.json", "subventions/index.json", "existant"),
    ("subventions_attribuant.schema.json", "subventions/attribuants/*.json", "existant"),
    ("subventions_annees.schema.json", "subventions/annees.json", "existant"),
    ("subventions_departements.schema.json", "subventions/departements.json", "existant"),
    ("subventions_beneficiaires.schema.json", "subventions/beneficiaires.json", "existant"),
    ("subventions_programmes.schema.json", "subventions/programmes.json", "existant"),
    # associations : jaunes PLF 2012-2025, fonds et fondations, reserve parlementaire (pipeline/associations.py)
    ("associations_index.schema.json", "associations/index.json", "existant"),
    ("associations_programme.schema.json", "associations/programmes/*.json", "existant"),
    ("associations_fonds_fondations.schema.json", "associations/fonds_fondations.json", "existant"),
    ("associations_reserve.schema.json", "associations/reserve/*.json", "existant"),
    # dette publique : encours, intérêts, détenteurs, financement (pipeline/dette.py)
    ("dette_index.schema.json", "dette/index.json", "existant"),
    ("dette_encours.schema.json", "dette/encours.json", "existant"),
    ("dette_interets.schema.json", "dette/interets.json", "existant"),
    ("dette_detenteurs.schema.json", "dette/detenteurs.json", "existant"),
    ("dette_financement.schema.json", "dette/financement.json", "existant"),
    # depenses fiscales et niches sociales (pipeline/niches.py)
    ("niches_mesures.schema.json", "niches/mesures.json", "existant"),
    ("niches_programmes.schema.json", "niches/programmes.json", "existant"),
    ("niches_sociales.schema.json", "niches/sociales.json", "existant"),
    ("niches_index.schema.json", "niches/index.json", "existant"),
    # contrôle (juridictions financières), influence (HATVP), aides aux entreprises (pipeline/controle.py)
    ("controle_index.schema.json", "controle/index.json", "existant"),
    ("controle_programmes.schema.json", "controle/publications/programmes.json", "existant"),
    ("controle_collectivites.schema.json", "controle/publications/collectivites/*.json", "existant"),
    ("controle_autres.schema.json", "controle/publications/autres.json", "existant"),
    ("controle_lobbying_organisations.schema.json", "controle/lobbying/organisations.json", "existant"),
    ("controle_lobbying_ministeres.schema.json", "controle/lobbying/ministeres.json", "existant"),
    ("controle_aides_entreprises.schema.json", "controle/aides_entreprises.json", "existant"),
    # rapports d'observations définitives des chambres régionales et territoriales 2020-2026 (pipeline/controle.py)
    ("controle_rod_crtc_index.schema.json", "controle/rod_crtc/index.json", "existant"),
    ("controle_rod_crtc_annee.schema.json", "controle/rod_crtc/[0-9][0-9][0-9][0-9].json", "existant"),
    # opérateurs de l'État et agences (pipeline/operateurs.py)
    ("operateurs.schema.json", "operateurs/operateurs.json", "existant"),
    ("operateurs_index.schema.json", "operateurs/index.json", "existant"),
    # la France et ses voisins : COFOG et prélèvements dans l'UE (pipeline/europe_comparaison.py)
    ("comparaison_index.schema.json", "comparaison/index.json", "existant"),
    ("comparaison_depenses.schema.json", "comparaison/depenses/*.json", "existant"),
    ("comparaison_prelevements.schema.json", "comparaison/prelevements.json", "existant"),
    ("comparaison_fiches.schema.json", "comparaison/fiches.json", "existant"),
    # traçabilité et décisions (pipeline/tracabilite.py, pipeline/decisions.py)
    ("tracabilite_noeud.schema.json", "tracabilite/programme_*.json", "existant"),
    ("tracabilite_noeud.schema.json", "tracabilite/noeud_*.json", "existant"),
    ("tracabilite_resume.schema.json", "tracabilite/resume.json", "existant"),
    ("decisions_programme.schema.json", "decisions/programme_*.json", "existant"),
    ("decisions_amendements_resume.schema.json", "decisions/amendements_resume.json", "existant"),
    ("decisions_scrutins.schema.json", "decisions/scrutins.json", "existant"),
    ("decisions_mouvements.schema.json", "decisions/mouvements_*.json", "existant"),
    ("decisions_coherence_plrg.schema.json", "decisions/coherence_plrg.json", "existant"),
    ("decisions_index.schema.json", "decisions/index.json", "existant"),
    # axe « Pres de chez moi » (pipeline/local.py)
    ("local_index.schema.json", "local/index.json", "existant"),
    ("local_geo.schema.json", "local/geo/*.json", "existant"),
    ("local_budget.schema.json", "local/budgets/communes/*.json", "existant"),
    ("local_budget.schema.json", "local/budgets/departements.json", "existant"),
    ("local_budget.schema.json", "local/budgets/regions.json", "existant"),
    ("local_budget_epci.schema.json", "local/budgets/epci/*.json", "existant"),
    ("local_fonctions_departements.schema.json", "local/budgets/fonctions/departements.json", "existant"),
    ("local_fonctions.schema.json", "local/budgets/fonctions/[0-9]*.json", "existant"),
    ("local_fonctions_communes.schema.json", "local/fonctions/[0-9]*.json", "existant"),   # local_fonctions.py
    ("local_fonctions_regions.schema.json", "local/fonctions/regions.json", "existant"),
    ("local_fonctions_index.schema.json", "local/fonctions/index.json", "existant"),
    ("local_dotations_communes.schema.json", "local/dotations/communes/*.json", "existant"),
    ("local_dotations_epci.schema.json", "local/dotations/epci.json", "existant"),
    ("local_dotations_departements.schema.json", "local/dotations/departements.json", "existant"),
    ("local_dotations_regions.schema.json", "local/dotations/regions.json", "existant"),
    ("local_taux.schema.json", "local/taux/*.json", "existant"),
    ("local_decisions_index.schema.json", "local/decisions/index.json", "existant"),
    ("local_decisions_collectivite.schema.json", "local/decisions/*/index.json", "existant"),
    ("local_decisions_annee.schema.json", "local/decisions/*/[0-9]*.json", "existant"),
    ("local_decisions_annee.schema.json", "local/decisions/*/inconnue*.json", "existant"),
    ("territoires_index.schema.json", "territoires/index.json", "existant"),   # territoires.py (contrat 2.25)
    ("territoires_departement.schema.json", "territoires/[0-9]*.json", "existant"),
    # numérique de l'État : panorama des grands projets (DINUM), France Relance, DITP, FTAP, FAST (numerique_etat.py)
    ("numerique_etat_index.schema.json", "numerique_etat/index.json", "existant"),
    ("numerique_etat_annees.schema.json", "numerique_etat/annees.json", "existant"),
    ("numerique_etat_panorama_projets.schema.json", "numerique_etat/panorama/projets.json", "existant"),
    ("numerique_etat_panorama_editions.schema.json", "numerique_etat/panorama/editions.json", "existant"),
    ("numerique_etat_panorama_ministeres.schema.json", "numerique_etat/panorama/ministeres.json", "existant"),
    ("numerique_etat_panorama_programmes.schema.json", "numerique_etat/panorama/programmes.json", "existant"),
    ("numerique_etat_france_relance.schema.json", "numerique_etat/fonds/france_relance.json", "existant"),
    ("numerique_etat_france_relance_dep.schema.json", "numerique_etat/fonds/france_relance/*.json", "existant"),
    ("numerique_etat_ditp.schema.json", "numerique_etat/fonds/ditp.json", "existant"),
    ("numerique_etat_ditp_itn7_dep.schema.json", "numerique_etat/fonds/ditp_itn7/*.json", "existant"),
    ("numerique_etat_ftap.schema.json", "numerique_etat/fonds/ftap.json", "existant"),
    ("numerique_etat_fast.schema.json", "numerique_etat/fonds/fast.json", "existant"),
    # etablissements de sante et medico-sociaux : FINESS, Open CCAM, prix des EHPAD (pipeline/sante_etablissements.py)
    ("sante_etablissements_index.schema.json", "sante_etablissements/index.json", "existant"),
    ("sante_etablissements_limites.schema.json", "sante_etablissements/limites.json", "existant"),
    ("sante_etablissements_departements.schema.json", "sante_etablissements/departements.json", "existant"),
    ("sante_etablissements_departement.schema.json", "sante_etablissements/departements/*.json", "existant"),
    ("sante_etablissements_hospi_diag.schema.json", "sante_etablissements/hospi_diag.json", "existant"),
    ("sante_etablissements_finances.schema.json", "sante_etablissements/finances_agregees.json", "existant"),
    # marchés publics de tous les acheteurs, DECP consolidées 2019-2025 (pipeline/marches.py)
    ("marches_index.schema.json", "marches/index.json", "existant"),
    ("marches_annees.schema.json", "marches/annees.json", "existant"),
    ("marches_categories.schema.json", "marches/categories.json", "existant"),
    ("marches_departements.schema.json", "marches/departements.json", "existant"),
    ("marches_departement.schema.json", "marches/departements/*.json", "existant"),
    ("marches_regions.schema.json", "marches/regions.json", "existant"),
    ("marches_secteurs.schema.json", "marches/secteurs.json", "existant"),
    ("marches_titulaires.schema.json", "marches/titulaires.json", "existant"),
    ("marches_acheteurs.schema.json", "marches/acheteurs.json", "existant"),
    # aide au développement : APD déclarée, AFD, OCDE, Expertise France, Proparco (pipeline/aide_developpement.py)
    ("aide_developpement_index.schema.json", "aide_developpement/index.json", "existant"),
    ("aide_developpement_apd_declaree.schema.json", "aide_developpement/apd_declaree.json", "existant"),
    ("aide_developpement_afd.schema.json", "aide_developpement/afd.json", "existant"),
    ("aide_developpement_ocde.schema.json", "aide_developpement/ocde.json", "existant"),
    ("aide_developpement_expertise_france.schema.json", "aide_developpement/expertise_france.json", "existant"),
    ("aide_developpement_proparco.schema.json", "aide_developpement/proparco.json", "existant"),
    # formation professionnelle : CPF, formation des élus, FIPHFP (pipeline/formation.py)
    ("formation_index.schema.json", "formation/index.json", "existant"),
    ("formation_cpf_mois.schema.json", "formation/cpf_mois.json", "existant"),
    ("formation_cpf_departements.schema.json", "formation/cpf_departements.json", "existant"),
    ("formation_cpf_certifications.schema.json", "formation/cpf_certifications.json", "existant"),
    ("formation_cpf_organismes.schema.json", "formation/cpf_organismes.json", "existant"),
    ("formation_cpf_usagers.schema.json", "formation/cpf_usagers.json", "existant"),
    ("formation_elus.schema.json", "formation/elus.json", "existant"),
    ("formation_fiphfp.schema.json", "formation/fiphfp.json", "existant"),
    # l'État actionnaire : dividendes, cessions, opérations en capital (pipeline/etat_actionnaire.py)
    ("etat_actionnaire_index.schema.json", "etat_actionnaire/index.json", "existant"),
    ("etat_actionnaire_flux.schema.json", "etat_actionnaire/flux.json", "existant"),
    ("etat_actionnaire_entites.schema.json", "etat_actionnaire/entites.json", "existant"),
    ("etat_actionnaire_societes_controlees.schema.json", "etat_actionnaire/societes_controlees.json", "existant"),
    # éducation et recherche : ANR, lycées, collectivités, étudiants (pipeline/education_recherche.py)
    ("education_recherche_index.schema.json", "education_recherche/index.json", "existant"),
    ("education_recherche_anr_etablissements.schema.json", "education_recherche/anr_etablissements.json", "existant"),
    ("education_recherche_anr_projets.schema.json", "education_recherche/anr_projets.json", "existant"),
    ("education_recherche_lycees.schema.json", "education_recherche/lycees/[0-9]*.json", "existant"),
    ("education_recherche_collectivites_esr.schema.json", "education_recherche/collectivites_esr.json", "existant"),
    ("education_recherche_etudiants.schema.json", "education_recherche/etudiants.json", "existant"),
    ("education_recherche_compte_education.schema.json", "education_recherche/compte_education.json", "existant"),
    # fonction publique : effectifs Insee, cabinets, conseils extérieurs, barème des élus (pipeline/fonction_publique.py)
    ("fonction_publique_index.schema.json", "fonction_publique/index.json", "existant"),
    ("fonction_publique_effectifs_series.schema.json", "fonction_publique/effectifs_series.json", "existant"),
    ("fonction_publique_emploi.schema.json", "fonction_publique/emploi.json", "existant"),
    ("fonction_publique_territoires.schema.json", "fonction_publique/territoires.json", "existant"),
    ("fonction_publique_ministeres.schema.json", "fonction_publique/ministeres.json", "existant"),
    ("fonction_publique_cabinets.schema.json", "fonction_publique/cabinets.json", "existant"),
    ("fonction_publique_conseils.schema.json", "fonction_publique/conseils.json", "existant"),
    ("fonction_publique_indemnites_elus.schema.json", "fonction_publique/indemnites_elus.json", "existant"),
    ("fonction_publique_remunerations.schema.json", "fonction_publique/remunerations.json", "existant"),
    # collectivités d'outre-mer 975, 977, 978, 986, 987, 988 (pipeline/outremer.py)
    ("outremer_index.schema.json", "outremer/index.json", "existant"),
    ("outremer_territoire.schema.json", "outremer/9[78][0-9].json", "existant"),
    ("outremer_budget_nc.schema.json", "outremer/988_budget.json", "existant"),
    # satellites locaux : syndicats, CCAS-CIAS, AOM et versement mobilité, eau (pipeline/local_satellites.py)
    ("local_satellites_index.schema.json", "local_satellites/index.json", "existant"),
    ("local_satellites_syndicats.schema.json", "local_satellites/syndicats/*.json", "existant"),
    ("local_satellites_ccas.schema.json", "local_satellites/ccas/*.json", "existant"),
    ("local_satellites_mobilite.schema.json", "local_satellites/mobilite/*.json", "existant"),
    ("local_satellites_eau.schema.json", "local_satellites/eau/*.json", "existant"),
    # contrôle et recouvrement : notifié, encaissé, estimations (pipeline/recouvrement.py)
    ("recouvrement_index.schema.json", "recouvrement/index.json", "existant"),
    ("recouvrement_controle_fiscal.schema.json", "recouvrement/controle_fiscal.json", "existant"),
    ("recouvrement_controle_urssaf.schema.json", "recouvrement/controle_urssaf.json", "existant"),
    ("recouvrement_impayes.schema.json", "recouvrement/impayes.json", "existant"),
    ("recouvrement_apurements_etat.schema.json", "recouvrement/apurements_etat.json", "existant"),
    ("recouvrement_estimations.schema.json", "recouvrement/estimations.json", "existant"),
    # justice et défense : établissements pénitentiaires, budget de la justice, ressorts, armement (pipeline/justice_defense.py)
    ("justice_defense_index.schema.json", "justice_defense/index.json", "existant"),
    ("justice_defense_prisons.schema.json", "justice_defense/prisons.json", "existant"),
    ("justice_defense_budget_justice.schema.json", "justice_defense/budget_justice.json", "existant"),
    ("justice_defense_ressorts.schema.json", "justice_defense/ressorts.json", "existant"),
    ("justice_defense_armement.schema.json", "justice_defense/armement.json", "existant"),
    # retraites par régime : retraités, pensions moyennes, cotisants publiés, CAS Pensions (pipeline/retraites.py)
    ("retraites_index.schema.json", "retraites/index.json", "existant"),
    ("retraites_regimes.schema.json", "retraites/regimes.json", "existant"),
    ("retraites_etat.schema.json", "retraites/etat.json", "existant"),
    # solidarités des départements : allocations et recettes rattachées (comptes OFGL), reste à charge calculé,
    # bénéficiaires de l'aide sociale départementale (DREES), écarts (pipeline/solidarites_departements.py)
    ("solidarites_departements_index.schema.json", "solidarites_departements/index.json", "existant"),
    ("solidarites_departements_comptes.schema.json", "solidarites_departements/comptes.json", "existant"),
    ("solidarites_departements_beneficiaires.schema.json", "solidarites_departements/beneficiaires.json", "existant"),
    ("solidarites_departements_ecarts.schema.json", "solidarites_departements/ecarts.json", "existant"),
    # fraîcheur des données : dernière collecte, millésime, calendrier officiel, statut (pipeline/fraicheur.py)
    ("fraicheur_index.schema.json", "fraicheur/index.json", "existant"),
    # fonds européens structurels et d'investissement : programmes, régions, thèmes, années, FRR, listes d'opérations
    # (pipeline/fonds_europeens.py)
    ("fonds_europeens_index.schema.json", "fonds_europeens/index.json", "existant"),
    ("fonds_europeens_programmes.schema.json", "fonds_europeens/programmes.json", "existant"),
    ("fonds_europeens_regions.schema.json", "fonds_europeens/regions.json", "existant"),
    ("fonds_europeens_themes.schema.json", "fonds_europeens/themes.json", "existant"),
    ("fonds_europeens_annees.schema.json", "fonds_europeens/annees.json", "existant"),
    ("fonds_europeens_frr.schema.json", "fonds_europeens/frr.json", "existant"),
    ("fonds_europeens_operations_index.schema.json", "fonds_europeens/operations.json", "existant"),
    ("fonds_europeens_operations.schema.json", "fonds_europeens/operations/*.json", "existant"),
    # aides aux entreprises : registre européen TAM, France 2030, France Relance, PGE (pipeline/aides_entreprises.py)
    ("aides_entreprises_index.schema.json", "aides_entreprises/index.json", "existant"),
    ("aides_entreprises_tam.schema.json", "aides_entreprises/tam.json", "existant"),
    ("aides_entreprises_france2030.schema.json", "aides_entreprises/france2030.json", "existant"),
    ("aides_entreprises_france_relance.schema.json", "aides_entreprises/france_relance.json", "existant"),
    ("aides_entreprises_pge.schema.json", "aides_entreprises/pge.json", "existant"),
    # logement : aides personnelles par aide et département, MaPrimeRénov', PTZ, renvois (pipeline/logement.py)
    ("logement_index.schema.json", "logement/index.json", "existant"),
    ("logement_aides_personnelles.schema.json", "logement/aides_personnelles/*.json", "existant"),
    ("logement_maprimerenov.schema.json", "logement/maprimerenov.json", "existant"),
    ("logement_ptz.schema.json", "logement/ptz.json", "existant"),
    # millésimes : exécution 2025 préparée, vérification des éditions attendues (pipeline/millesimes.py)
    ("millesimes_index.schema.json", "millesimes/index.json", "existant"),
    ("arbre_etat.schema.json", "millesimes/execution2025/*.json", "existant"),
    # revenus et impôt sur le revenu par commune : IRCOM, Filosofi (pipeline/revenus_communes.py)
    ("revenus_communes_index.schema.json", "revenus_communes/index.json", "existant"),
    ("revenus_communes_communes.schema.json", "revenus_communes/communes/*.json", "existant"),
    ("revenus_communes_tranches.schema.json", "revenus_communes/tranches/*/*.json", "existant"),
    # séries longues : indice des prix, PIB, dépenses par fonction depuis 2005 (pipeline/series.py)
    ("series_index.schema.json", "series/index.json", "existant"),
    ("series_fonctions.schema.json", "series/fonctions.json", "existant"),
    # agriculture : PAC par département (2005-2009), FEADER et cofinancement, budget de l'État (pipeline/agriculture.py)
    ("agriculture_index.schema.json", "agriculture/index.json", "existant"),
    ("agriculture_pac_departements.schema.json", "agriculture/pac_departements.json", "existant"),
    ("agriculture_developpement_rural.schema.json", "agriculture/developpement_rural.json", "existant"),
    ("agriculture_etat.schema.json", "agriculture/etat.json", "existant"),
    # transports : AFITF, concours publics au ferroviaire, programmes, versement mobilité (pipeline/transports.py)
    ("transports_index.schema.json", "transports/index.json", "existant"),
    ("transports_afitf.schema.json", "transports/afitf.json", "existant"),
    ("transports_ferroviaire.schema.json", "transports/ferroviaire.json", "existant"),
    ("transports_programmes.schema.json", "transports/programmes.json", "existant"),
    ("transports_versement_mobilite.schema.json", "transports/versement_mobilite.json", "existant"),
    # énergie et climat : charges de service public (CRE), boucliers, programmes 345 et 174, chèque énergie (pipeline/energie_climat.py)
    ("energie_climat_index.schema.json", "energie_climat/index.json", "existant"),
    ("energie_climat_charges_service_public.schema.json", "energie_climat/charges_service_public.json", "existant"),
    ("energie_climat_boucliers.schema.json", "energie_climat/boucliers.json", "existant"),
    ("energie_climat_budget.schema.json", "energie_climat/budget.json", "existant"),
    ("energie_climat_cheque_energie.schema.json", "energie_climat/cheque_energie.json", "existant"),
    # culture et médias : budget par action, audiovisuel public, aides à la presse, CNC (pipeline/culture_medias.py)
    ("culture_medias_index.schema.json", "culture_medias/index.json", "existant"),
    ("culture_medias_budget.schema.json", "culture_medias/budget.json", "existant"),
    ("culture_medias_audiovisuel.schema.json", "culture_medias/audiovisuel.json", "existant"),
    ("culture_medias_presse.schema.json", "culture_medias/presse.json", "existant"),
    ("culture_medias_cnc.schema.json", "culture_medias/cnc.json", "existant"),
    # sport : programmes 219 et 350, Agence nationale du sport, CNDS 2015, coût public des Jeux (pipeline/sport.py)
    ("sport_index.schema.json", "sport/index.json", "existant"),
    ("sport_budget.schema.json", "sport/budget.json", "existant"),
    ("sport_federations.schema.json", "sport/federations.json", "existant"),
    ("sport_cnds_2015.schema.json", "sport/cnds_2015.json", "existant"),
    ("sport_jop.schema.json", "sport/jop.json", "existant"),
    # emploi : comptes de l'Unédic, France Travail, activité partielle, aides à l'embauche (pipeline/emploi.py)
    ("emploi_index.schema.json", "emploi/index.json", "existant"),
    ("emploi_unedic.schema.json", "emploi/unedic.json", "existant"),
    ("emploi_france_travail.schema.json", "emploi/france_travail.json", "existant"),
    ("emploi_activite_partielle.schema.json", "emploi/activite_partielle.json", "existant"),
    ("emploi_aides_embauche.schema.json", "emploi/aides_embauche.json", "existant"),
    # accueil du jeune enfant : places, complément de mode de garde, action sociale des CAF (pipeline/petite_enfance.py)
    ("petite_enfance_index.schema.json", "petite_enfance/index.json", "existant"),
    ("petite_enfance_nationales.schema.json", "petite_enfance/nationales.json", "existant"),
    ("petite_enfance_departement.schema.json", "petite_enfance/departements/*.json", "existant"),
    # eau et environnement : agences de l'eau, ADEME, Fonds vert (pipeline/eau_environnement.py)
    ("eau_environnement_index.schema.json", "eau_environnement/index.json", "existant"),
    ("eau_environnement_agences_eau.schema.json", "eau_environnement/agences_eau.json", "existant"),
    ("eau_environnement_ademe.schema.json", "eau_environnement/ademe.json", "existant"),
    ("eau_environnement_fonds_vert.schema.json", "eau_environnement/fonds_vert.json", "existant"),
    # sécurité intérieure : police, gendarmerie, sécurité civile, sécurité routière, compte des amendes (pipeline/securite_interieure.py)
    ("securite_interieure_index.schema.json", "securite_interieure/index.json", "existant"),
    ("securite_interieure_budget.schema.json", "securite_interieure/budget.json", "existant"),
    ("securite_interieure_effectifs.schema.json", "securite_interieure/effectifs.json", "existant"),
    ("securite_interieure_amendes.schema.json", "securite_interieure/amendes.json", "existant"),
    # douane et accises : produit par accise, recettes perçues par la douane, affectation (pipeline/douanes_accises.py)
    ("douanes_accises_index.schema.json", "douanes_accises/index.json", "existant"),
    ("douanes_accises_produits.schema.json", "douanes_accises/produits.json", "existant"),
    ("douanes_accises_collecte.schema.json", "douanes_accises/collecte.json", "existant"),
    ("douanes_accises_affectation.schema.json", "douanes_accises/affectation.json", "existant"),
    # pouvoirs publics : dotations de la mission, budgets des institutions, barèmes par fonction (pipeline/pouvoirs_publics.py)
    ("pouvoirs_publics_index.schema.json", "pouvoirs_publics/index.json", "existant"),
    ("pouvoirs_publics_dotations.schema.json", "pouvoirs_publics/dotations.json", "existant"),
    ("pouvoirs_publics_budgets_institutions.schema.json", "pouvoirs_publics/budgets_institutions.json", "existant"),
    ("pouvoirs_publics_indemnites.schema.json", "pouvoirs_publics/indemnites.json", "existant"),
    # assurance maladie : dépenses remboursées par grand poste, prescriptions et honoraires par département, ONDAM
    # par sous-objectif (pipeline/assurance_maladie_territoires.py)
    ("assurance_maladie_territoires_index.schema.json", "assurance_maladie_territoires/index.json", "existant"),
    ("assurance_maladie_territoires_postes.schema.json", "assurance_maladie_territoires/postes.json", "existant"),
    ("assurance_maladie_territoires_departements.schema.json", "assurance_maladie_territoires/departements.json", "existant"),
    ("assurance_maladie_territoires_ondam.schema.json", "assurance_maladie_territoires/ondam.json", "existant"),
    # fiscalité locale par commune, séries 2010 à aujourd'hui : taux et produits du REI (pipeline/fiscalite_locale_series.py)
    ("fiscalite_locale_series_index.schema.json", "fiscalite_locale_series/index.json", "existant"),
    ("fiscalite_locale_series_communes.schema.json", "fiscalite_locale_series/communes/*.json", "existant"),
    # immobilier de l'État : parc, valeur, cessions, loyers, compte (pipeline/immobilier_etat.py)
    ("immobilier_etat_index.schema.json", "immobilier_etat/index.json", "existant"),
    ("immobilier_etat_parc.schema.json", "immobilier_etat/parc.json", "existant"),
    ("immobilier_etat_valeur.schema.json", "immobilier_etat/valeur.json", "existant"),
    ("immobilier_etat_cessions.schema.json", "immobilier_etat/cessions.json", "existant"),
    ("immobilier_etat_loyers.schema.json", "immobilier_etat/loyers.json", "existant"),
    ("immobilier_etat_compte.schema.json", "immobilier_etat/compte.json", "existant"),
    # territoires comparables : typologies des communes et croisements prédéfinis (pipeline/typologies.py)
    ("typologies_index.schema.json", "typologies/index.json", "existant"),
    ("typologies_croisement.schema.json", "typologies/croisements/*.json", "existant"),
    ("typologies_communes.schema.json", "typologies/communes/*.json", "existant"),
    # organisations reliées d'une source à l'autre : SIREN, Splink, fiches et recherche (pipeline/entites.py)
    ("entites_index.schema.json", "entites/index.json", "existant"),
    ("entites_fiches.schema.json", "entites/fiches/*.json", "existant"),
    ("entites_recherche.schema.json", "entites/recherche/*.json", "existant"),
    ("entites_recherche_globale.schema.json", "entites/recherche_globale.json", "existant"),
    # performance : objectifs, indicateurs, cibles et réalisés par programme reliés aux crédits ; baromètre des
    # résultats de l'action publique par département (pipeline/performance.py)
    ("performance_index.schema.json", "performance/index.json", "existant"),
    ("performance_correspondance.schema.json", "performance/correspondance.json", "existant"),
    ("performance_programme.schema.json", "performance/programmes/*.json", "existant"),
    ("performance_barometre_index.schema.json", "performance/barometre/index.json", "existant"),
    ("performance_barometre_zone.schema.json", "performance/barometre/[0-9F]*.json", "existant"),
    # application des lois : lois, mesures d'application, délais (pipeline/application_lois.py)
    ("application_lois_index.schema.json", "application_lois/index.json", "existant"),
    ("application_lois_finances.schema.json", "application_lois/lois_finances.json", "existant"),
    ("application_lois_lois.schema.json", "application_lois/lois/*.json", "existant"),
    ("application_lois_mesures.schema.json", "application_lois/mesures/*.json", "existant"),
    # projets subventionnés par l'État : Fonds vert par commune, badges ACV et PVD, liens vers les dotations (pipeline/projets_subventionnes.py)
    ("projets_subventionnes_index.schema.json", "projets_subventionnes/index.json", "existant"),
    ("projets_subventionnes_departement.schema.json", "projets_subventionnes/[0-9]*.json", "existant"),
    # investissement réalisé par commune (balances DGFiP) et délibérations publiées au format national
    # (pipeline/investissement_communes.py, pipeline/deliberations.py)
    ("investissement_communes_index.schema.json", "investissement_communes/index.json", "existant"),
    ("investissement_communes_communes.schema.json", "investissement_communes/communes/*.json", "existant"),
    ("deliberations_index.schema.json", "deliberations/index.json", "existant"),
    ("deliberations_collectivite.schema.json", "deliberations/collectivites/*.json", "existant"),
    ("deliberations_budgets.schema.json", "deliberations/budgets.json", "existant"),
    # qui a voté tes impôts : articles, scrutins publics nominatifs, amendements adoptés par impôt (pipeline/qui_a_vote.py)
    ("qui_a_vote_index.schema.json", "qui_a_vote/index.json", "existant"),
    ("qui_a_vote_impot.schema.json", "qui_a_vote/impot_*.json", "existant"),
    ("qui_a_vote_votes.schema.json", "qui_a_vote/votes_*.json", "existant"),
    ("qui_a_vote_scrutins.schema.json", "qui_a_vote/scrutins.json", "existant"),
    ("qui_a_vote_departement.schema.json", "qui_a_vote/departements/*.json", "existant"),
]

# Arbres decoupes : le controle des liens 'fichier' s'applique a ces schemas
SCHEMAS_ARBRE = {"arbre_etat.schema.json", "arbre_administrations.schema.json"}

# Exemples du contrat du module de calcul (docs/exemples/<prefixe>*.json)
EXEMPLES_SCHEMAS = [("profil.schema.json", "profil_*.json"), ("resultat.schema.json", "resultat_*.json")]


def charger_jsonschema():
    try:
        importlib.import_module("referencing")
        return importlib.import_module("jsonschema")
    except ImportError:
        print("jsonschema absent : installation (pip install jsonschema)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "jsonschema>=4.18"])
        importlib.invalidate_caches()
        return importlib.import_module("jsonschema")


def best_match(erreurs_):
    from jsonschema.exceptions import best_match as bm
    return bm(erreurs_)


_REGISTRE = None


def registre():
    """Tous les schemas de docs/schemas, indexes par $id (references croisees, ex. commun.schema.json)."""
    global _REGISTRE
    if _REGISTRE is None:
        from referencing import Registry, Resource
        ressources = []
        for p in sorted(SCHEMAS.glob("*.schema.json")):
            doc = json.loads(p.read_text(encoding="utf-8"))
            ressources.append((doc["$id"], Resource.from_contents(doc)))
        _REGISTRE = Registry().with_resources(ressources)
    return _REGISTRE


_VALIDATEURS: dict = {}


def validateur(js, nom_schema: str):
    """Validateur compile une seule fois par schema et par processus (cache)."""
    v = _VALIDATEURS.get(nom_schema)
    if v is None:
        schema = json.loads((SCHEMAS / nom_schema).read_text(encoding="utf-8"))
        cls = js.validators.validator_for(schema)
        cls.check_schema(schema)
        v = _VALIDATEURS[nom_schema] = cls(schema, registry=registre(), format_checker=cls.FORMAT_CHECKER)
    return v


_CACHE_OK: set = set()        # empreintes (schemas + fichier) deja conformes au schema
_EMPREINTE_SCHEMAS = None


def chemin_cache() -> Path:
    """Cache hors depot des fichiers deja conformes : meme contenu et memes schemas => schema non rejoue.
    Les controles hors schema (liens, conservation, sommes de parts) sont toujours rejoues."""
    import hashlib
    import tempfile
    base = os.environ.get("OVMI_CACHE_CONTRAT") or tempfile.gettempdir()
    return Path(base) / f"ovmi_valider_contrat_{hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]}.txt"


def empreinte(nom_schema: str, contenu: bytes) -> str:
    import hashlib
    global _EMPREINTE_SCHEMAS
    if _EMPREINTE_SCHEMAS is None:
        h = hashlib.sha256(importlib.metadata.version("jsonschema").encode())   # meme moteur de validation
        for p in sorted(SCHEMAS.glob("*.schema.json")):
            h.update(p.name.encode() + p.read_bytes())
        _EMPREINTE_SCHEMAS = h.hexdigest()
    return hashlib.sha256((_EMPREINTE_SCHEMAS + nom_schema).encode() + contenu).hexdigest()


def _init_processus(cache: set) -> None:
    global _CACHE_OK
    _CACHE_OK = cache


def _valider_lot(lot: tuple[str, list[str]]) -> list[tuple[str, list[str], str | None]]:
    """Valide un lot de fichiers d'un meme schema (execute dans un processus de travail) :
    (chemin, erreurs, empreinte si conforme au schema, pour le cache)."""
    nom_schema, chemins = lot
    v = validateur(charger_jsonschema(), nom_schema)
    sortie = []
    for c in chemins:
        p = Path(c)
        contenu = p.read_bytes()
        try:
            doc = json.loads(contenu.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            sortie.append((c, [f"JSON illisible ({exc})"], None))
            continue
        cle = empreinte(nom_schema, contenu)
        errs = [] if cle in _CACHE_OK else erreurs(v, doc)
        cle = cle if not errs else None
        if nom_schema in SCHEMAS_ARBRE:
            errs += liens_arbre(p, doc)
        elif not errs:
            errs += liens_fichiers(p, doc) + conservation_groupes(doc) + sommes_de_parts(nom_schema, doc)
        sortie.append((c, errs, cle))
    return sortie


def erreurs(v, doc, limite: int = 5) -> list[str]:
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        if e.context:  # oneOf / anyOf : montrer l'erreur la plus precise
            e = best_match(e.context)
        chemin = "/" + "/".join(str(p) for p in e.absolute_path)
        out.append(f"{chemin} : {e.message[:200]}")
        if len(out) >= limite:
            out.append("...")
            break
    return out


def liens_arbre(chemin: Path, doc: dict) -> list[str]:
    """Controle hors schema : chaque 'fichier' reference par un noeud existe."""
    manquants = []

    def parcourir(n):
        if "fichier" in n and not (SITE / n["fichier"]).exists():
            manquants.append(f"{n['id']} -> {n['fichier']} introuvable")
        for e in n.get("enfants", []):
            parcourir(e)

    parcourir(doc)
    return manquants


def liens_fichiers(chemin: Path, doc) -> list[str]:
    """Controle hors schema : toute cle `fichier*` qui designe un .json pointe vers un fichier present.

    Regle commune : chemin relatif a site/data/. Exception tolere (signalee au contrat) : vie_politique/annees.json
    ecrit ses liens relatifs a son propre dossier.
    """
    manquants = []

    def parcourir(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if (k.startswith("fichier") and isinstance(x, str) and x.endswith(".json") and "<" not in x):
                    if not ((SITE / x).exists() or (chemin.parent / x).exists()):
                        manquants.append(f"lien {k} -> {x} introuvable")
                else:
                    parcourir(x)
        elif isinstance(v, list):
            for x in v:
                parcourir(x)

    parcourir(doc)
    return manquants[:5]


def conservation_groupes(doc) -> list[str]:
    """Controle hors schema : dans un groupe de beneficiaires, top + autres + exclus = total (a 1 euro pres)."""
    ecarts = []

    def parcourir(v, chemin):
        if isinstance(v, dict):
            if "top" in v and "exclus_personnes_physiques_ou_non_identifies" in v:
                total = v.get("total_eur", v.get("total_source_eur"))
                somme = (sum(t["montant_eur"] for t in v["top"]) + v["autres_personnes_morales"]["montant_eur"]
                         + v["autres_non_verifies"]["montant_eur"]
                         + v["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"])
                if total is None or abs(somme - total) > 1:
                    ecarts.append(f"{chemin or '/'} : conservation rompue (somme {somme:.2f} != total {total})")
            for k, x in v.items():
                parcourir(x, f"{chemin}/{k}")

    parcourir(doc, "")
    return ecarts


def sommes_de_parts(nom_schema: str, doc) -> list[str]:
    """Controle hors schema : parts d'un prelevement source (affectation) et parts communales (taxe fonciere) = 1."""
    ecarts = []
    if nom_schema == "prelevements_affectation.schema.json":
        for pid, pr in doc["prelevements"].items():
            somme = sum(v["part"] for v in pr["ventilation"])
            if pr["statut"] == "sourcee" and abs(somme - 1) > 1e-4:
                ecarts.append(f"/prelevements/{pid} : somme des parts {somme:.6f} != 1")
            for v in pr["ventilation"]:
                if v["destinataire"] not in doc["destinataires"]:
                    ecarts.append(f"/prelevements/{pid} : destinataire inconnu {v['destinataire']}")
    elif nom_schema == "prelevements_taxe_fonciere_dep.schema.json":
        for code, v in doc["communes"].items():
            if v is not None and abs(sum(v[6:12]) - 1) > 1e-3:
                ecarts.append(f"/communes/{code} : parts 6 a 11 = {sum(v[6:12]):.4f} != 1")
    return ecarts[:5]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="un fichier de site/data couvert par aucun schema fait echouer la validation")
    ap.add_argument("--sans-cache", action="store_true",
                    help="rejouer le schema meme pour un fichier inchange deja conforme")
    ap.add_argument("--processus", type=int, default=0,
                    help="processus de validation en parallele (defaut : coeurs disponibles, 8 au plus ; 1 = en serie)")
    args = ap.parse_args()
    js = charger_jsonschema()

    n_ok = n_ko = n_prevus = n_manquants = 0
    couverts: set[Path] = set()
    # Lots de 40 fichiers par schema, valides en parallele par processus ; l'affichage garde l'ordre de FICHIERS.
    par_motif, lots = [], []
    for nom_schema, motif, etat in FICHIERS:
        chemins = sorted(Path(p) for p in glob.glob(str(SITE / motif)))
        couverts.update(chemins)
        par_motif.append((nom_schema, motif, etat, chemins))
        lot, octets = [], 0
        for p in chemins:   # lots d'au plus 40 fichiers ou 4 Mo : le cout de validation suit la taille
            lot.append(str(p))
            octets += p.stat().st_size
            if len(lot) >= 40 or octets >= 4_000_000:
                lots.append((octets, nom_schema, lot))
                lot, octets = [], 0
        if lot:
            lots.append((octets, nom_schema, lot))
    # Les plus gros lots d'abord, un lot par tache : aucun processus ne recoit seul tous les fichiers lourds.
    lots = [(nom, lot) for _, nom, lot in sorted(lots, key=lambda x: -x[0])]
    nb = args.processus or min(8, os.cpu_count() or 1)
    fichier_cache = chemin_cache()
    cache = set()
    if not args.sans_cache and fichier_cache.exists():
        cache = set(fichier_cache.read_text(encoding="ascii", errors="ignore").split())
    _init_processus(cache)
    if nb > 1 and len(lots) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=nb, initializer=_init_processus, initargs=(cache,)) as pool:
            resultats = list(pool.map(_valider_lot, lots, chunksize=1))
    else:
        resultats = [_valider_lot(lot) for lot in lots]
    erreurs_par_fichier = {c: errs for lot in resultats for c, errs, _ in lot}
    try:   # seules les empreintes des fichiers presents sont gardees (le cache ne grossit pas)
        tmp = fichier_cache.with_name(fichier_cache.name + f".{os.getpid()}.tmp")
        tmp.write_text("\n".join(sorted(cle for lot in resultats for _, _, cle in lot if cle)) + "\n",
                       encoding="ascii")
        os.replace(tmp, fichier_cache)
    except OSError:
        pass
    for nom_schema, motif, etat, chemins in par_motif:
        if not chemins:
            if etat == "prevu":
                n_prevus += 1
                print(f"PREVU    {motif} : absent (schema {nom_schema} pret)")
            else:
                n_manquants += 1
                print(f"MANQUANT {motif} : fichier attendu absent")
            continue
        ko_motif = 0
        for p in chemins:
            errs = erreurs_par_fichier[str(p)]
            if errs:
                ko_motif += 1
                print(f"KO       {p.relative_to(ROOT)}")
                for e in errs:
                    print(f"           {e}")
        n_ko += ko_motif
        n_ok += len(chemins) - ko_motif
        if not args.quiet and not ko_motif:
            print(f"OK       {motif} ({len(chemins)} fichier{'s' if len(chemins) > 1 else ''})")

    orphelins = sorted(set(SITE.rglob("*.json")) - couverts)
    for p in orphelins[:10]:
        print(f"ORPHELIN {p.relative_to(ROOT)} : aucun schema ne couvre ce fichier (completer FICHIERS)")
    if len(orphelins) > 10:
        print(f"ORPHELIN ... et {len(orphelins) - 10} autres")

    for nom_schema, motif in EXEMPLES_SCHEMAS:
        v = validateur(js, nom_schema)
        for p in sorted(EXEMPLES.glob(motif)):
            errs = erreurs(v, json.loads(p.read_text(encoding="utf-8")))
            if errs:
                n_ko += 1
                print(f"KO       {p.relative_to(ROOT)}")
                for e in errs:
                    print(f"           {e}")
            else:
                n_ok += 1
                if not args.quiet:
                    print(f"OK       {p.relative_to(ROOT)}")

    print(f"\nBilan : {n_ok} conformes, {n_ko} non conformes, {n_manquants} manquants, {n_prevus} prevus absents, "
          f"{len(orphelins)} orphelins{' (bloquants : --strict)' if args.strict else ''}")
    return 1 if (n_ko or n_manquants or (args.strict and orphelins)) else 0


if __name__ == "__main__":
    sys.exit(main())
