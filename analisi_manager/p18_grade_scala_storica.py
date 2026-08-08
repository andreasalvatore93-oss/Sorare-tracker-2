"""Scala storica del grade per (lega,ruolo) -- BRIEF_SONNET_GRADE_SCALA_
STORICA_2026-08-08.txt, sez.2.

Oggi (GRADE_SCALE='gruppo', comportamento di produzione) media e sd del
grade si calcolano DENTRO il gruppo (lega,ruolo) della singola giornata: se
il gruppo ha meno di 2 carte col grade, z=0 (grade ignorato); se ne ha
esattamente 2, z e' meccanicamente +-1 qualunque sia la distanza vera.

Qui si costruisce una scala ALTERNATIVA: media e sd del grade calcolate
sullo STORICO multi-giornata per (lega,ruolo), con fallback (ruolo) e
(globale) quando le osservazioni sono poche. build_formazione_globale.py la
usa SOLO se GRADE_SCALE=storica (default 'gruppo', invariato).

Fonti (le stesse 6+1 dell'indice grade, p12_backtest_formazione_grade.
carica_indice_grade + p12_backtest_manager_grade.carica_indice_grade_esteso):
danno slug -> lista (data, grade_num). Qui serve anche LEGA e RUOLO per
osservazione:
  - lega: analizza_gw.indice_lega() (slug -> lega)
  - ruolo: NON e' salvato per-osservazione nelle fonti crowss (formato
    nested); si usa il ruolo PIU' FREQUENTE con cui quello slug compare
    nelle carte dei file dati_globali/manager_*.json (stesso universo dati
    di tutto il filone G). Approssimazione dichiarata: un giocatore che ha
    cambiato ruolo (D7 CLAUDE.md) conta con un solo ruolo qui, quello
    maggioritario nelle carte osservate -- non e' walk-forward sul ruolo,
    e' un'approssimazione accettata per una scala AGGREGATA, non per la
    predizione riga per riga.

Uso:
  python analisi_manager/p18_grade_scala_storica.py
  (scrive generatore_formazioni/dati/grade_scala_storica.json, versione
  "tutta la storia", quella che la produzione userebbe con GRADE_SCALE=storica)

Funzioni riusabili da altri script (walk-forward per il backtest, Passo 1/2
del brief): costruisci_scala(osservazioni, cutoff=None).
"""
import os
import sys
import io
import json
import glob
import collections
import datetime

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21
import p12_backtest_manager_grade as M
import analizza_gw as AG

SOGLIA_LEGA_RUOLO = 100
SOGLIA_RUOLO = 500
OUT_PATH = os.path.join(ROOT, 'generatore_formazioni', 'dati', 'grade_scala_storica.json')


def slug_to_ruolo_maggioritario():
    """slug -> ROLE_CODE piu' frequente nelle carte di dati_globali/manager_*.json."""
    conteggi = collections.defaultdict(collections.Counter)
    for path in sorted(glob.glob(os.path.join(ROOT, 'dati_globali', 'manager_*.json'))):
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        for righe in (d.get('giornate') or {}).values():
            for f_ in righe:
                for c in (f_.get('carte') or []):
                    cod = M.ROLE_CODE.get(c.get('ruolo'))
                    if cod:
                        conteggi[c.get('slug')][cod] += 1
    return {slug: cnt.most_common(1)[0][0] for slug, cnt in conteggi.items()}


def costruisci_osservazioni():
    """Lista di dict {slug, lega, ruolo, data, grade_num} da tutte le fonti
    storiche (versione estesa, 7 fonti). Scarta chi non ha lega o ruolo noti
    (dichiarato in output, non silenzioso)."""
    idx_grade, data_min = M.carica_indice_grade_esteso()
    lega_di = AG.indice_lega()
    ruolo_di = slug_to_ruolo_maggioritario()

    osservazioni = []
    scarti = collections.Counter()
    for slug, entries in idx_grade.items():
        lega = lega_di.get(slug)
        ruolo = ruolo_di.get(slug)
        for data, grade_num in entries:
            if lega is None:
                scarti['senza_lega'] += 1
                continue
            if ruolo is None:
                scarti['senza_ruolo'] += 1
                continue
            osservazioni.append({'slug': slug, 'lega': lega, 'ruolo': ruolo,
                                 'data': data, 'grade_num': grade_num})
    return osservazioni, scarti, data_min


def _media_sd(vals):
    n = len(vals)
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    return m, sd, n


def costruisci_scala(osservazioni, cutoff=None):
    """cutoff: stringa 'YYYY-MM-DD' o None. Se dato, usa SOLO osservazioni
    con data < cutoff (walk-forward, niente leakage). Ritorna la struttura
    da salvare/consultare: per_lega_ruolo, per_ruolo, globale, meta."""
    if cutoff is not None:
        oss = [o for o in osservazioni if o['data'] < cutoff]
    else:
        oss = osservazioni

    per_lr = collections.defaultdict(list)
    per_r = collections.defaultdict(list)
    tutti = []
    for o in oss:
        per_lr[(o['lega'], o['ruolo'])].append(o['grade_num'])
        per_r[o['ruolo']].append(o['grade_num'])
        tutti.append(o['grade_num'])

    out_lr = {}
    n_lega_ruolo_ok = 0
    for (lega, ruolo), vals in per_lr.items():
        if len(vals) >= SOGLIA_LEGA_RUOLO:
            m, sd, n = _media_sd(vals)
            out_lr[f'{lega}|{ruolo}'] = {'mean': m, 'sd': sd, 'n': n}
            n_lega_ruolo_ok += 1

    out_r = {}
    n_ruolo_ok = 0
    for ruolo, vals in per_r.items():
        if len(vals) >= SOGLIA_RUOLO:
            m, sd, n = _media_sd(vals)
            out_r[ruolo] = {'mean': m, 'sd': sd, 'n': n}
            n_ruolo_ok += 1

    if tutti:
        m, sd, n = _media_sd(tutti)
        globale = {'mean': m, 'sd': sd, 'n': n}
    else:
        globale = None

    # quante coppie (lega,ruolo) REALI (tutte quelle viste, non solo quelle
    # sopra soglia) userebbero ciascun livello di fallback
    livelli = collections.Counter()
    for (lega, ruolo), vals in per_lr.items():
        if len(vals) >= SOGLIA_LEGA_RUOLO:
            livelli['lega_ruolo'] += 1
        elif len(per_r.get(ruolo, [])) >= SOGLIA_RUOLO:
            livelli['ruolo'] += 1
        elif globale is not None:
            livelli['globale'] += 1

    return {
        'per_lega_ruolo': out_lr, 'per_ruolo': out_r, 'globale': globale,
        'meta': {'cutoff': cutoff, 'n_osservazioni_usate': len(oss),
                 'n_gruppi_lega_ruolo_totali': len(per_lr),
                 'n_gruppi_lega_ruolo_sopra_soglia': n_lega_ruolo_ok,
                 'n_ruoli_sopra_soglia': n_ruolo_ok,
                 'coppie_lega_ruolo_per_livello_fallback': dict(livelli),
                 'soglia_lega_ruolo': SOGLIA_LEGA_RUOLO, 'soglia_ruolo': SOGLIA_RUOLO},
    }


def main():
    osservazioni, scarti, data_min = costruisci_osservazioni()
    print('=' * 78)
    print('SCALA STORICA DEL GRADE per (lega,ruolo)')
    print('=' * 78)
    print(f'osservazioni totali (slug,data,grade) dalle fonti storiche: '
          f'{len(osservazioni) + sum(scarti.values())}')
    print(f'scarti: {dict(scarti)}')
    print(f'osservazioni utilizzabili (lega+ruolo noti): {len(osservazioni)}')
    print(f'prima data nelle fonti: {data_min}')

    scala = costruisci_scala(osservazioni, cutoff=None)
    print(f'\ngruppi (lega,ruolo) osservati: {scala["meta"]["n_gruppi_lega_ruolo_totali"]}')
    print(f'  di cui sopra soglia {SOGLIA_LEGA_RUOLO} (usano scala lega+ruolo): '
          f'{scala["meta"]["n_gruppi_lega_ruolo_sopra_soglia"]}')
    print(f'ruoli sopra soglia {SOGLIA_RUOLO} (fallback ruolo): {scala["meta"]["n_ruoli_sopra_soglia"]}')
    print(f'ripartizione per livello di fallback: {scala["meta"]["coppie_lega_ruolo_per_livello_fallback"]}')
    print(f'\nscala globale: {scala["globale"]}')
    print('\nscala per ruolo (sopra soglia):')
    for ruolo, v in sorted(scala['per_ruolo'].items()):
        print(f'  {ruolo:4s} mean={v["mean"]:.2f} sd={v["sd"]:.2f} n={v["n"]}')
    print(f'\nscala per (lega,ruolo) (sopra soglia, {len(scala["per_lega_ruolo"])} coppie) -- prime 15:')
    for k, v in list(sorted(scala['per_lega_ruolo'].items(), key=lambda kv: -kv[1]['n']))[:15]:
        print(f'  {k:30s} mean={v["mean"]:.2f} sd={v["sd"]:.2f} n={v["n"]}')

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as fh:
        json.dump(scala, fh, ensure_ascii=False, indent=2)
    print(f'\nsalvato: {OUT_PATH}')

    # anche la versione RICALCOLATA sui dati attuali della scala globale
    # aggregata semplice (media/sd complessivi), per confronto col numero
    # citato nel brief (media 2.95, sd 1.65) -- RICALCOLATA, non copiata.
    print(f'\ncontrollo (brief cita media~2.95 sd~1.65 su 5.792 osservazioni con lega nota): '
          f'qui, su {len(osservazioni)} osservazioni CON lega+ruolo noti: '
          f'mean={scala["globale"]["mean"]:.2f} sd={scala["globale"]["sd"]:.2f} '
          f'n={scala["globale"]["n"]}')


if __name__ == '__main__':
    sys.exit(main() or 0)
