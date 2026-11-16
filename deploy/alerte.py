"""Alerte apres un echec de la collecte hebdomadaire (ovmi-collecte-alerte.service).

Toujours : message d'erreur dans journalctl (journalctl -u ovmi-collecte-alerte).
Optionnel : si GITHUB_TOKEN est defini, ouvre une issue sur OVMI_GITHUB_DEPOT (ou commente
l'issue ouverte existante, etiquette « collecte-echec ») avec la fin du journal du jour.
Les lignes mentionnant la zone restreinte ou un secret ne sont jamais publiees.
"""
from __future__ import annotations

import os
import re
import socket
import sys
from datetime import date
from pathlib import Path

ETIQUETTE = "collecte-echec"
MASQUE = re.compile(r"(?i)_restreint|secret|token|access_key|password|authorization")
UTILES = re.compile(r"ERREUR|ECHEC|ESPACE|ARRET|CONFIGURATION|Traceback|Error|=== |stockage :|sources collectees")


def extrait_journal(racine: Path, n: int = 40) -> str:
    journaux = sorted((racine / "journaux").glob("collecte-*.log"))
    if not journaux:
        return "(aucun journal de collecte trouve)"
    lignes = journaux[-1].read_text(encoding="utf-8", errors="replace").splitlines()
    garde = [l for l in lignes if UTILES.search(l) and not MASQUE.search(l)]
    fin = [l for l in lignes[-15:] if not MASQUE.search(l)]
    vu, sortie = set(), []
    for l in garde[-n:] + fin:
        if l not in vu:
            vu.add(l)
            sortie.append(l[:300])
    return "\n".join(sortie)


def ouvrir_issue(depot: str, jeton: str, titre: str, corps: str) -> str:
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {jeton}", "Accept": "application/vnd.github+json",
                      "User-Agent": "ovmi-collecte-alerte"})
    api = f"https://api.github.com/repos/{depot}"
    ouvertes = s.get(f"{api}/issues", params={"labels": ETIQUETTE, "state": "open"}, timeout=30)
    ouvertes.raise_for_status()
    if ouvertes.json():
        num = ouvertes.json()[0]["number"]
        s.post(f"{api}/issues/{num}/comments", json={"body": f"**{titre}**\n\n{corps}"}, timeout=30).raise_for_status()
        return f"commentaire ajoute a l'issue #{num}"
    r = s.post(f"{api}/issues", json={"title": titre, "body": corps, "labels": [ETIQUETTE]}, timeout=30)
    r.raise_for_status()
    return f"issue #{r.json()['number']} ouverte"


def main() -> int:
    racine = Path(os.environ.get("OVMI_RACINE", "/var/lib/ovmi"))
    titre = f"Collecte hebdomadaire en echec ({socket.gethostname()}, {date.today().isoformat()})"
    extrait = extrait_journal(racine)
    print(f"ALERTE : {titre}\n{extrait}", file=sys.stderr)
    jeton = os.environ.get("GITHUB_TOKEN", "").strip()
    if not jeton:
        return 0
    corps = ("La collecte hebdomadaire s'est terminee avec un code non nul.\n\n"
             f"```\n{extrait}\n```\n\nDetail sur le VPS : `journalctl -u ovmi-collecte -n 200`.")
    try:
        print(ouvrir_issue(os.environ.get("OVMI_GITHUB_DEPOT", "MoonEyes/Ou-vont-mes-impots"), jeton, titre, corps))
    except Exception as exc:  # l'alerte ne doit pas masquer l'echec initial
        print(f"issue GitHub impossible : {type(exc).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
