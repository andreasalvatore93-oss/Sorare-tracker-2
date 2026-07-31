"""AUDIT (31/07): verifica che i file predict duplicati per lega abbiano
DAVVERO gli stessi parametri di produzione, cioe' che nessuna propagazione
passata abbia lasciato indietro una lega.

Estrae per ogni lega/ruolo i valori delle costanti che contano e segnala
ogni divergenza rispetto al valore di maggioranza (MLS e' il riferimento
canonico: e' li' che si applicano i fix prima di propagarli).

Uso: python formazione_mls/diagnostics/audit_coerenza_leghe.py
"""
import os
import re
import glob
from collections import defaultdict

PRIOR_RE = r'max\(0\.0,\s*([\d.]+\s*\+\s*[\d.]+)\s*\*\s*presence_rate\)'

# ruolo -> (nome file, [pattern da estrarre])
PATTERNS = {
    'gk': ('test_gk.py', [
        ('HALF_LIFE_GAMES', r'^HALF_LIFE_GAMES\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('TREND_INTENSITY', r'^TREND_INTENSITY\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SHRINK_K_OUTLIER_GK', r'^\s*SHRINK_K_OUTLIER_GK\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('MEDIA_RUOLO_GK_PRIOR', r'^\s*MEDIA_RUOLO_GK_PRIOR\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SPLIT_SHRINK_K_GK', r'SPLIT_SHRINK_K_GK\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('prior_dinamico', PRIOR_RE),
    ]),
    'def': ('test_def.py', [
        ('HALF_LIFE_GAMES', r'^HALF_LIFE_GAMES\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('TREND_INTENSITY', r'^TREND_INTENSITY\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SHRINK_K_OUTLIER_DEF', r'^\s*SHRINK_K_OUTLIER_DEF\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('MEDIA_RUOLO_DEF_PRIOR', r'^\s*MEDIA_RUOLO_DEF_PRIOR\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SPLIT_SHRINK_K', r'SPLIT_SHRINK_K\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('prior_dinamico', PRIOR_RE),
    ]),
    'mid': ('test_mid.py', [
        ('HALF_LIFE_GAMES', r'^HALF_LIFE_GAMES\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('TREND_INTENSITY', r'^TREND_INTENSITY\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SHRINK_K_OUTLIER_MID', r'^\s*SHRINK_K_OUTLIER_MID\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('MEDIA_RUOLO_MID_PRIOR', r'^\s*MEDIA_RUOLO_MID_PRIOR\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SPLIT_SHRINK_K', r'SPLIT_SHRINK_K\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('prior_dinamico', PRIOR_RE),
    ]),
    'fwd': ('test_mls_fwd_all.py', [
        ('HALF_LIFE_GAMES', r'^HALF_LIFE_GAMES\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('TREND_INTENSITY', r'^TREND_INTENSITY\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SHRINK_K_OUTLIER_FWD', r'^\s*SHRINK_K_OUTLIER_FWD\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('SPLIT_SHRINK_K', r'SPLIT_SHRINK_K\s*=\s*([\d.]+)\s*(?:#.*)?$'),
        ('prior_dinamico', PRIOR_RE),
    ]),
}


def estrai(path, patterns):
    try:
        with open(path, encoding='utf-8') as f:
            testo = f.read()
    except OSError:
        return None
    out = {}
    for nome, pat in patterns:
        m = re.search(pat, testo, re.MULTILINE)
        out[nome] = re.sub(r'\s+', ' ', m.group(1)).strip() if m else 'ASSENTE'
    return out


def main():
    leghe = sorted(os.path.basename(d)[len('formazione_'):]
                    for d in glob.glob('formazione_*') if os.path.isdir(d))
    problemi = 0
    for ruolo, (fname, patterns) in PATTERNS.items():
        print(f"\n{'=' * 78}\nRUOLO {ruolo.upper()} ({fname})\n{'=' * 78}")
        valori = {}
        for lega in leghe:
            path = os.path.join(f'formazione_{lega}', 'predict', fname)
            if not os.path.isfile(path):
                continue
            v = estrai(path, patterns)
            if v:
                valori[lega] = v
        if not valori:
            print("  nessun file trovato")
            continue
        rif = valori.get('mls')
        for nome, _pat in patterns:
            conteggi = defaultdict(list)
            for lega, v in valori.items():
                conteggi[v[nome]].append(lega)
            atteso = rif[nome] if rif else max(conteggi, key=lambda k: len(conteggi[k]))
            diversi = {val: lg for val, lg in conteggi.items() if val != atteso}
            if not diversi:
                print(f"  {nome:<24} OK  ({atteso}) su {len(valori)} leghe")
            else:
                problemi += 1
                print(f"  {nome:<24} DIVERGENZA — MLS={atteso}")
                for val, lg in sorted(diversi.items()):
                    print(f"      {val!r}: {lg}")
    print(f"\n{'=' * 78}\nDivergenze totali trovate: {problemi}")


if __name__ == '__main__':
    main()
