"""Horodatage reproductible des sorties du pipeline.

Deux productions sur le même entrepôt doivent donner des fichiers identiques octet pour octet
(tests/test_reproductibilite.py). Une date écrite dans une sortie est donc la date de la dernière collecte de
l'entrepôt (data/lake/manifest.json), jamais l'heure du passage ; SOURCE_DATE_EPOCH (convention des constructions
reproductibles) la remplace si elle est définie. Seul site/data/meta.json garde l'heure réelle du passage
(`genere_le`, qui ne déclenche jamais de commit à lui seul).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFESTE = ROOT / "data" / "lake" / "manifest.json"


def date_sources(*domaines: str, avec_heure: bool = False) -> str:
    """Date (ou date-heure UTC) de la collecte la plus récente des domaines demandés (tous si aucun)."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        dt = datetime.fromtimestamp(int(epoch), timezone.utc)
    else:
        dates = []
        try:
            entrees = json.loads(MANIFESTE.read_text(encoding="utf-8")).values()
        except (OSError, ValueError, AttributeError):
            entrees = []
        for e in entrees:
            if isinstance(e, dict) and e.get("collecte_le") and (not domaines or e.get("domaine") in domaines):
                d = datetime.fromisoformat(str(e["collecte_le"]).replace("Z", "+00:00"))
                dates.append(d if d.tzinfo else d.replace(tzinfo=timezone.utc))
        dt = max(dates).astimezone(timezone.utc) if dates else datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if avec_heure else dt.date().isoformat()
