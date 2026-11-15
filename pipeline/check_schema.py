"""Detecte un changement de schema a la source.

Compare data/raw/<id>.schema.json (schema declare par la source au dernier
telechargement) a schemas/<id>.json (reference validee par un humain).
  python pipeline/check_schema.py          -> code 1 et rapport si ecart
  python pipeline/check_schema.py --accept -> la situation actuelle devient la reference
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
REF = ROOT / "schemas"


def main() -> int:
    accept = "--accept" in sys.argv
    REF.mkdir(exist_ok=True)
    ecarts = []
    for current_path in sorted(RAW.glob("*.schema.json")):
        name = current_path.name.replace(".schema.json", "")
        current = json.loads(current_path.read_text(encoding="utf-8"))["fields"]
        ref_path = REF / f"{name}.json"
        if accept or not ref_path.exists():
            ref_path.write_text(json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(f"reference ecrite : {ref_path.relative_to(ROOT)}")
            continue
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        for champ in sorted(set(ref) | set(current)):
            if champ not in current:
                ecarts.append(f"- {name} : champ `{champ}` disparu")
            elif champ not in ref:
                ecarts.append(f"- {name} : nouveau champ `{champ}` ({current[champ]})")
            elif ref[champ] != current[champ]:
                ecarts.append(f"- {name} : type de `{champ}` {ref[champ]} -> {current[champ]}")
    if ecarts:
        rapport = "Changement de schema detecte a la source :\n" + "\n".join(ecarts)
        print(rapport)
        (ROOT / "schema_drift.md").write_text(rapport + "\n\nSi c'est attendu : `python pipeline/check_schema.py --accept`.\n", encoding="utf-8")
        return 1
    print("schemas conformes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
