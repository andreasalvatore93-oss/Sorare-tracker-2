#!/usr/bin/env python3
"""
consolida_dati_globali.py

Raccoglie in un'UNICA cartella (dati_globali/) tutti i dati grezzi utili al tuning
del modello, COPIANDOLI da ogni pipeline formazione_<campionato>/output/ senza
spostare/toccare gli originali (le pipeline continuano a funzionare identiche).

Rigenerabile a comando: cancella e ricostruisce dati_globali/ ad ogni esecuzione.

Cosa consolida:
- grid_search:  formazione_<champ>/output/<champ>_<role>_calibration/grid_search/<slug>_grid.json
                -> dati_globali/grid_search/<champ>/<role>/<slug>_grid.json
                (risultati grid search 72 combo per giocatore, input di
                 aggregate_grid_search.py / bootstrap_stability.py sul campione unito)
- detail_cache: formazione_<champ>/output/<champ>_<role>_{all,calibration}/.cache/<slug>_detail_cache.json
                -> dati_globali/detail_cache/<champ>/<role>/<slug>_detail_cache.json
                (detailedScore per partita: base per analisi locali — level_score,
                 correlazioni, impatto live score, ecc.)

Produce anche dati_globali/manifest.json con i conteggi per campionato/ruolo.

Uso:  python consolida_dati_globali.py
"""
from __future__ import annotations
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "dati_globali"
ROLES = ("gk", "def", "mid", "fwd")
# <champ>_<role>_<suffix>  (champ puo' contenere cifre: germania2, giappone100, ...)
DIR_RE = re.compile(r"^(?P<champ>.+)_(?P<role>gk|def|mid|fwd)_(?P<suffix>all|calibration|discovery)$")


def parse_output_dir(name: str):
    m = DIR_RE.match(name)
    if not m:
        return None
    return m.group("champ"), m.group("role"), m.group("suffix")


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    (DEST / "grid_search").mkdir(parents=True, exist_ok=True)
    (DEST / "detail_cache").mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {}

    def bump(champ: str, role: str, key: str, n: int = 1) -> None:
        manifest.setdefault(champ, {}).setdefault(role, {"grid": 0, "detail_cache": 0})
        manifest[champ][role][key] += n

    n_grid = n_cache = 0
    for out_dir in sorted(ROOT.glob("formazione_*/output/*")):
        if not out_dir.is_dir():
            continue
        parsed = parse_output_dir(out_dir.name)
        if not parsed:
            continue
        champ, role, _suffix = parsed

        # grid_search
        for src in out_dir.glob("grid_search/*_grid.json"):
            dst_dir = DEST / "grid_search" / champ / role
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst_dir / src.name)
            bump(champ, role, "grid")
            n_grid += 1

        # detail_cache (.cache/*_detail_cache.json)
        for src in out_dir.glob(".cache/*_detail_cache.json"):
            dst_dir = DEST / "detail_cache" / champ / role
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            # se lo stesso giocatore compare in _all e _calibration, tiene il file piu' grande
            if dst.exists() and dst.stat().st_size >= src.stat().st_size:
                continue
            was_new = not dst.exists()
            shutil.copy2(src, dst)
            if was_new:
                bump(champ, role, "detail_cache")
                n_cache += 1

    totals = {
        "generato": datetime.now(timezone.utc).isoformat(),
        "grid_files_totali": n_grid,
        "detail_cache_totali": n_cache,
        "campionati": sorted(manifest.keys()),
        "per_campionato": manifest,
    }
    (DEST / "manifest.json").write_text(json.dumps(totals, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Consolidamento in {DEST.relative_to(ROOT)}/")
    print(f"  grid_search:  {n_grid} file")
    print(f"  detail_cache: {n_cache} file (giocatori distinti)")
    print(f"  campionati:   {len(manifest)} -> {', '.join(sorted(manifest.keys()))}")


if __name__ == "__main__":
    main()
