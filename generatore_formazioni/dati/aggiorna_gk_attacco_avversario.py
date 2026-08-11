"""Costruisce la tabella squadra -> forza d'attacco (media storica secca dei
gol fatti), usata dal correttivo GK_ATT_AVV in build_formazione_globale.py
(flag GK_ATT_AVV_ENABLED, spento di default).

STORIA DEL METODO (11/08/2026, contestazione dell'utente sulla media
storica secca): l'utente ha obiettato che le squadre ruotano
giocatori/allenatori e una media piatta non ha senso. Testato
(analisi_manager/dati/gk_halflife_2026-08-11.json, n=881, stesso campione
aggregato di Opus): finestre CORTE (ultime 5-10 partite, hard cut o
decadimento esponenziale) fanno PEGGIO della storia intera, in modo
monotono -- half-life lunghe (40-80) pareggiano la secca sulla
CORRELAZIONE (+0,105 vs +0,104), ma nel BACKTEST VERO (Binario 2,
analisi_manager/p24_binario2_ga.py, 337 GW aggregate, bootstrap sul delta
appaiato) la media secca vince su tutti i numeri: +4.413 essenze (vs +3.900
half-life), bootstrap positivo nel 95,9% (vs 91,3%), IC95% [-487;+9.387]
(vs [-1.768;+9.426]). Decisione dell'utente (11/08/2026): tenere la media
secca (equilibrio migliore misurato), ma resa DINAMICA (vedi sotto) per
rispondere all'obiezione sul turnover. Pendenza di regressione: k=-4.26,
media globale att_medio 1.400 (n=2.612, §11 del report). Dettaglio:
docs/handoff/RISPOSTA_OPUS_CORRELAZIONI_2026-08-13.txt §11-12.

DINAMICO (11/08/2026): questo script ora fa un aggiornamento INCREMENTALE,
non ricalcola da zero. Guarda l'ultima data gia' coperta dai file gol
estratti e scarica solo le partite NUOVE (query pubblica nodes(ids), stesso
metodo di analisi_manager/p40_estrai_gol_squadre_crowss.py), le aggiunge al
file della stagione corrente, poi ricalcola la tabella. Va rilanciato prima
di ogni run di generazione formazioni per essere davvero aggiornato (non
succede da solo/schedulato: vedi nota in fondo su dove andrebbe agganciato).

Uso: python generatore_formazioni/dati/aggiorna_gk_attacco_avversario.py
Legge/aggiorna: analisi_manager/dati/gol_squadre_archivio_2025-26_*.json
Legge (sola lettura): analisi_manager/dati/gol_squadre_archivio_2023_25_*.json
Produce: generatore_formazioni/dati/gk_attacco_avversario.json
"""
import os
import sys
import json
import glob
import time
import collections
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

CORRENTE_GLOB = 'analisi_manager/dati/gol_squadre_archivio_2025-26_*.json'
STORICO_GLOB = 'analisi_manager/dati/gol_squadre_archivio_2023_25_*.json'
OUT = os.path.join('generatore_formazioni', 'dati', 'gk_attacco_avversario.json')
MIN_STORICO = 4


def _ultimo_file(pattern):
    trovati = sorted(glob.glob(pattern))
    return trovati[-1] if trovati else None


def _aggiorna_incrementale():
    """Estende il file della stagione corrente con le partite nuove
    (successive all'ultima data gia' coperta), stesse squadre di sempre.
    Ritorna il path del file (aggiornato o creato)."""
    from analisi_manager.p42_estrai_gol_tutte_squadre_archivio import squadre_archivio
    from analisi_manager.p40_estrai_gol_squadre_crowss import estrai_gol

    f_corrente = _ultimo_file(CORRENTE_GLOB)
    esistenti = json.load(open(f_corrente, encoding='utf-8')) if f_corrente else {}
    ultima_data = max((r['date'] for r in esistenti.values()), default='2025-08-01')
    print(f"file corrente: {f_corrente or '(nessuno, primo run)'}  ultima data coperta: {ultima_data}")

    _giocatori, squadre = squadre_archivio()
    nuove = {}
    for root, _dirs, files in os.walk('.'):
        if not root.endswith('.game_log_cache'):
            continue
        for fn in files:
            if not fn.endswith('_gamelog.json'):
                continue
            try:
                d = json.load(open(os.path.join(root, fn), encoding='utf-8'))
            except Exception:
                continue
            for v in (d or {}).values():
                g = (v or {}).get('anyGame') or {}
                gid = g.get('id')
                data = (g.get('date') or '')[:10]
                if not gid or not data or data <= ultima_data or gid in esistenti:
                    continue
                if g.get('statusTyped') != 'played':
                    continue
                casa = (g.get('homeTeam') or {}).get('slug')
                fuori = (g.get('awayTeam') or {}).get('slug')
                if casa not in squadre and fuori not in squadre:
                    continue
                nuove[gid] = {'date': data, 'home': casa, 'away': fuori}

    print(f"partite nuove trovate in cache (dopo {ultima_data}): {len(nuove)}")
    if nuove:
        t0 = time.time()
        gol = estrai_gol(nuove.keys())
        print(f"gol estratti: {len(gol)}/{len(nuove)}  in {time.time()-t0:.0f}s")
        for gid, meta in nuove.items():
            g = gol.get(gid, {})
            esistenti[gid] = {**meta, **g}

    out_path = f_corrente or f'analisi_manager/dati/gol_squadre_archivio_2025-26_{datetime.date.today().isoformat()}.json'
    json.dump(esistenti, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"file corrente aggiornato: {out_path}  ({len(esistenti)} partite totali)")
    return out_path


def main():
    f_corrente = _aggiorna_incrementale()
    f_storico = _ultimo_file(STORICO_GLOB)
    gol_files = [f_corrente] + ([f_storico] if f_storico else [])

    fatti = collections.defaultdict(list)  # squadra -> [(data, gol)]
    n_partite = 0
    for gf in gol_files:
        gol = json.load(open(gf, encoding='utf-8'))
        for g in gol.values():
            h, a, d = g.get('home'), g.get('away'), g.get('date')
            hg, ag = g.get('home_goals'), g.get('away_goals')
            if hg is None or ag is None or not h or not a or not d:
                continue
            fatti[h].append((d, hg))
            fatti[a].append((d, ag))
            n_partite += 1
    for v in fatti.values():
        v.sort()
    print(f"file usati: {gol_files}")
    print(f"partite totali: {n_partite}  squadre: {len(fatti)}")

    # Due formule pre-registrate (11/08/2026, PRIMA di vedere i dati nuovi
    # 7-11 agosto, per non scegliere a posteriori su cosa esce meglio):
    #   'att_medio' = storica secca, tutta la storia disponibile
    #   'att_u10'   = secca sulle ultime 10 partite (scelta dell'utente,
    #                 "quella che mi convince di piu'"), nessun half-life
    N_ULTIME = 10
    tabella = {}
    for sq, partite in fatti.items():
        if len(partite) < MIN_STORICO:
            continue
        gols = [g for _d, g in partite]
        entry = {'att_medio': round(sum(gols) / len(gols), 3), 'n_partite': len(partite)}
        if len(gols) >= N_ULTIME:
            ultime = gols[-N_ULTIME:]
            entry['att_u10'] = round(sum(ultime) / len(ultime), 3)
        tabella[sq] = entry
    print(f"squadre con storico >= {MIN_STORICO} partite: {len(tabella)}")
    n_con_u10 = sum(1 for v in tabella.values() if 'att_u10' in v)
    print(f"  di cui con >= {N_ULTIME} partite (att_u10 calcolabile): {n_con_u10}")

    tutti = [v['att_medio'] for v in tabella.values()]
    print(f"media att_medio fra le squadre (storica secca): {sum(tutti)/len(tutti):.3f}")

    out_obj = {
        '_generato': datetime.date.today().isoformat(),
        '_min_storico': MIN_STORICO,
        '_n_ultime': N_ULTIME,
        '_metodo': 'due formule pre-registrate: att_medio (storica secca) e att_u10 (ultime 10), refresh incrementale',
        '_fonte': gol_files,
        'squadre': tabella,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out_obj, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"salvato: {OUT}")


if __name__ == '__main__':
    main()
