# -*- coding: utf-8 -*-
"""Costruisce le due tabelle usate dal correttivo "gruppo grade esteso"
(build_formazione_globale.py, flag GRADE_GROUP_STORICA_ENABLED, SPENTO di
default -- filone "gruppo grade esteso alla giornata", priorita' 2,
11-12/08/2026, docs/HANDOFF_UNIFICATO_MODELLO_SCOUTING.md §8bis-bis).

STATO (12/08/2026): il flag e' PRONTO ma SPENTO. Opus ha verificato la
ricetta col placebo (il voto ha segnale vero, p<=0,048) ma ha detto
testualmente "pronta per il fuori campione pre-registrato, NON per la
produzione diretta" -- il test fuori campione (GW5/6/7, chiude 25/08/2026,
vedi analisi_manager/p57_grade_fuoricampo_preregistrato.py) NON e' ancora
stato fatto. NON accendere GRADE_GROUP_STORICA_ENABLED prima di quel test.

Fonte (decisa da Opus il 12/08): i `consiglio_*.txt` di TUTTE le leghe/
ruoli, deduplicati per (lega,codice,slug,kickoff) -- stessa popolazione
che la produzione punteggia davvero, NON l'archivio backtest (biased).
Tabella VOTO: media/sd del grade per (lega,ruolo), grade agganciato via
l'indice condiviso (stesse fonti di analisi_manager/p12_backtest_
formazione_grade.carica_indice_grade). Tabella SD_ATTESO: media/sd
dell'atteso CALIBRATO per (lega,ruolo), con fix (celle n<2 rimosse,
ricadono sul livello ruolo -- soglie alte tipo 100/500 PEGGIORANO, vedi
§8bis-bis "Fix (i)+(ii)", NON aggiungerle).

Uso: python generatore_formazioni/dati/aggiorna_grade_scala_produzione.py
Zero query di rete (legge solo file locali: consiglio_*.txt + indice
grade condiviso, gia' scaricato da fetch_grade_gw.py altrove).
Produce: generatore_formazioni/dati/grade_scala_produzione.json,
         generatore_formazioni/dati/sd_atteso_produzione.json
Rilanciare prima di ogni run di generazione (stesso schema di
aggiorna_gk_attacco_avversario.py) quando il flag verra' acceso: le
tabelle vanno tenute aggiornate, non sono un dato congelato una volta per
sempre (a differenza degli snapshot _cutoff_ usati nel test fuori campione,
che restano intenzionalmente fermi al 12/08/2026).
"""
import os
import sys
import io
import glob
import json
import collections
import importlib.util

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # solo per carica_indice_grade/grade_in_finestra, zero rete


def _import_module(name, rel_path):
    path = os.path.join(ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bff = _import_module('mls_build_formazione_finale_prod', 'formazione_mls/build_formazione_finale.py')

OUT_VOTO = os.path.join('generatore_formazioni', 'dati', 'grade_scala_produzione.json')
OUT_SD = os.path.join('generatore_formazioni', 'dati', 'sd_atteso_produzione.json')
SOGLIA_LEGA_RUOLO_VOTO = 30
LEAGUES_ROOT_GLOB = os.path.join(ROOT, 'formazione_*', 'output', '*_all')


def _discover_consiglio_dirs():
    """Stessa scoperta di build_formazione_globale._discover_leagues(), ma
    qui autosufficiente (niente dipendenza dal modulo generatore, per non
    ricaricare 800+ righe solo per due tabelle)."""
    dirs = []
    for role_dir in sorted(glob.glob(LEAGUES_ROOT_GLOB)):
        champ_dir = os.path.basename(os.path.dirname(os.path.dirname(role_dir)))
        if not champ_dir.startswith('formazione_'):
            continue
        league = champ_dir[len('formazione_'):]
        base = os.path.basename(role_dir)
        for suffix, codice in (('_gk_all', 'GK'), ('_def_all', 'DEF'), ('_mid_all', 'MID'), ('_fwd_all', 'FWD')):
            if base.endswith(suffix):
                dirs.append((league, codice, role_dir))
    return dirs


def costruisci_righe():
    scelte = {}  # (lega,codice,slug,kickoff) -> (ts, atteso_raw)
    for lega, codice, abs_dir in _discover_consiglio_dirs():
        for path in sorted(glob.glob(os.path.join(abs_dir, 'consiglio_*.txt'))):
            ts = os.path.basename(path)  # ordine lessicografico = ordine temporale (nome contiene data_ora)
            for row in bff.parse_consiglio(path):
                slug, kickoff, atteso_raw = row.get('slug'), row.get('kickoff'), row.get('atteso')
                if slug is None or kickoff is None or atteso_raw is None:
                    continue
                chiave = (lega, codice, slug, kickoff)
                prec = scelte.get(chiave)
                if prec is None or ts > prec[0]:
                    scelte[chiave] = (ts, atteso_raw)
    righe = [{'lega': lega, 'codice': codice, 'slug': slug, 'kickoff': kickoff, 'atteso_raw': ar}
             for (lega, codice, slug, kickoff), (_ts, ar) in scelte.items()]
    return righe


def calibra(valore, ruolo, calib_per_ruolo):
    a, b = calib_per_ruolo.get(ruolo, (37.0, 0.7))
    return round(a + b * valore, 1)


def media_sd(vals):
    n = len(vals)
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    return m, sd, n


def main():
    righe = costruisci_righe()
    print(f'righe consiglio distinte (lega,codice,slug,kickoff): {len(righe)}')

    # calibrazione: stessa CALIB_PER_RUOLO di build_formazione_globale.py
    # (duplicata qui per non caricare tutto il modulo generatore -- se
    # cambia LA', va cambiata anche qui: e' un valore di produzione, non
    # una scoperta di questo script).
    calib_per_ruolo = {
        'GK':  (float(os.environ.get('CALIB_A_GK', '35.78')), float(os.environ.get('CALIB_B_GK', '0.264'))),
        'DEF': (float(os.environ.get('CALIB_A_DEF', '7.28')), float(os.environ.get('CALIB_B_DEF', '0.831'))),
        'MID': (float(os.environ.get('CALIB_A_MID', '11.61')), float(os.environ.get('CALIB_B_MID', '0.740'))),
        'FWD': (float(os.environ.get('CALIB_A_FWD', '8.40')), float(os.environ.get('CALIB_B_FWD', '0.789'))),
    }
    for r in righe:
        r['_cal'] = calibra(r['atteso_raw'], r['codice'], calib_per_ruolo)

    # --- tabella SD_ATTESO (dispersione dell'atteso calibrato) ---
    per_lr = collections.defaultdict(list)
    per_r = collections.defaultdict(list)
    tutti = []
    for r in righe:
        per_lr[(r['lega'], r['codice'])].append(r['_cal'])
        per_r[r['codice']].append(r['_cal'])
        tutti.append(r['_cal'])
    conteggio = {k: len(v) for k, v in per_lr.items()}
    out_lr_sd = {f'{lg}|{cod}': {'mean': media_sd(v)[0], 'sd': media_sd(v)[1], 'n': media_sd(v)[2]}
                 for (lg, cod), v in per_lr.items() if len(v) >= 2}  # fix (i): n<2 rimosse
    out_r_sd = {cod: {'mean': media_sd(v)[0], 'sd': media_sd(v)[1], 'n': media_sd(v)[2]}
                for cod, v in per_r.items()}
    m, sd, n = media_sd(tutti)
    globale_sd = {'mean': m, 'sd': sd, 'n': n}
    n_celle_tolte = sum(1 for k, v in per_lr.items() if len(v) < 2)
    print(f'sd_atteso: {len(out_lr_sd)} celle lega-ruolo (tolte {n_celle_tolte} con n<2), '
          f'globale sd={sd:.2f} n={n}')

    with open(OUT_SD, 'w', encoding='utf-8') as fh:
        json.dump({'per_lega_ruolo': out_lr_sd, 'per_ruolo': out_r_sd, 'globale': globale_sd,
                   'meta': {'fonte': 'consiglio_*.txt (dedup lega,codice,slug,kickoff)',
                            'n_righe': len(righe), 'fix_i_celle_n_minore_2_rimosse': n_celle_tolte}},
                  fh, ensure_ascii=False, indent=2)
    print(f'salvato: {OUT_SD}')

    # --- tabella VOTO (media/sd del grade, stessa popolazione) ---
    idx_grade, data_min = S21.carica_indice_grade()
    per_lr_g = collections.defaultdict(list)
    per_r_g = collections.defaultdict(list)
    tutti_g = []
    n_senza_grade = 0
    for r in righe:
        gn = S21.grade_in_finestra(idx_grade, r['slug'], r['kickoff'][:10])
        if gn is None:
            n_senza_grade += 1
            continue
        per_lr_g[(r['lega'], r['codice'])].append(gn)
        per_r_g[r['codice']].append(gn)
        tutti_g.append(gn)

    out_lr_g = {f'{lg}|{cod}': {'mean': media_sd(v)[0], 'sd': media_sd(v)[1], 'n': media_sd(v)[2]}
                for (lg, cod), v in per_lr_g.items() if len(v) >= SOGLIA_LEGA_RUOLO_VOTO}
    out_r_g = {cod: {'mean': media_sd(v)[0], 'sd': media_sd(v)[1], 'n': media_sd(v)[2]}
               for cod, v in per_r_g.items()}
    m, sd, n = media_sd(tutti_g)
    globale_g = {'mean': m, 'sd': sd, 'n': n}
    print(f'voto: {len(out_lr_g)} celle lega-ruolo sopra soglia {SOGLIA_LEGA_RUOLO_VOTO}, '
          f'{len(tutti_g)}/{len(righe)} righe con grade agganciato ({n_senza_grade} senza), '
          f'globale mean={m:.2f} sd={sd:.2f}')

    with open(OUT_VOTO, 'w', encoding='utf-8') as fh:
        json.dump({'per_lega_ruolo': out_lr_g, 'per_ruolo': out_r_g, 'globale': globale_g,
                   'meta': {'fonte': 'consiglio_*.txt + indice grade condiviso',
                            'soglia_lega_ruolo': SOGLIA_LEGA_RUOLO_VOTO,
                            'n_righe_input': len(righe), 'n_con_grade': len(tutti_g),
                            'n_senza_grade': n_senza_grade, 'prima_data_grade': data_min}},
                  fh, ensure_ascii=False, indent=2)
    print(f'salvato: {OUT_VOTO}')


if __name__ == '__main__':
    sys.exit(main() or 0)
