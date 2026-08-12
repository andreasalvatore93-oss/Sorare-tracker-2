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
POOL_ARCHIVIO = 'archivio_ufficiale/aggregato/binario2_pool_rows.json'

# CHI HO GIA' LETTO, E QUANTO ERA GROSSO (12/08/2026). Piccolo (~400 KB) e
# COMMITTATO apposta: e' quello che evita di rileggere 337 MB di cache ad ogni
# run. Per ogni file di game-log tiene la sua dimensione in byte e la squadra
# del giocatore che ne e' uscita. Al giro dopo si guarda solo la dimensione
# (una stat, microsecondi): se e' identica il file non e' cambiato, quindi non
# puo' contenere partite che non abbiamo gia' visto, e non lo si apre.
#
# Perche' la DIMENSIONE e non la data di modifica: il checkout riscrive le
# date, quindi l'mtime direbbe "tutto nuovo" ad ogni run. La dimensione invece
# dipende dal contenuto: un game-log che guadagna una partita cresce sempre.
#
# LIMITE MISURATO (12/08/2026, run 31643914743): la dimensione NON attraversa
# i sistemi operativi. L'indice costruito su Windows ha fatto centro solo su
# 197 file su 6.565 girando su ubuntu, perche' git converte i fine riga in
# checkout (autocrlf): lo stesso game-log pesa 62.430 byte su Windows e 60.272
# su Linux -- esattamente 2.158 byte di differenza, cioe' un byte per ognuno
# dei suoi 2.158 a capo. Non e' un guasto e si ripara da solo: la run
# ricostruisce l'indice e lo committa, e dalla successiva i conti tornano
# (l'ambiente di produzione e' uno solo). Se un domani si mescolassero
# davvero due sistemi, la chiave giusta sarebbe l'hash del blob di git
# (`git ls-files -s`), che e' il contenuto e non dipende dai fine riga.
VISTI = os.path.join('generatore_formazioni', 'dati', '_gamelog_visti.json')
VISTI_VERSIONE = 1


def _ultimo_file(pattern):
    trovati = sorted(glob.glob(pattern))
    return trovati[-1] if trovati else None


def _carica_visti():
    try:
        d = json.load(open(VISTI, encoding='utf-8'))
        if d.get('versione') == VISTI_VERSIONE:
            return d.get('file') or {}
    except (OSError, ValueError):
        pass
    return {}


def _scansiona_cache(ultima_data):
    """Una sola passeggiata sulla cache dei game-log, saltando i file che non
    sono cambiati dall'ultima volta.

    Ritorna (partite_candidate, squadra_per_slug).

    Prima di oggi qui si passava DUE volte sugli stessi 6.432 file (337 MB):
    una per ricostruire l'indice da 20 MB di p36 (che serviva solo a sapere in
    che squadra gioca ognuno) e una per cercare le partite nuove. Tre minuti
    per trovare, testualmente, zero partite nuove.
    """
    visti = _carica_visti()
    nuovi_visti = {}
    candidate = {}
    squadra_per_slug = {}
    n_letti = n_saltati = 0

    for root, _dirs, files in os.walk('.'):
        if not root.endswith('.game_log_cache'):
            continue
        for fn in files:
            if not fn.endswith('_gamelog.json'):
                continue
            path = os.path.join(root, fn).replace(os.sep, '/').lstrip('./')
            slug = fn[:-len('_gamelog.json')]
            try:
                dim = os.path.getsize(path)
            except OSError:
                continue
            prec = visti.get(path)
            if prec and prec[0] == dim:
                # Identico all'ultimo giro: le sue partite le abbiamo gia'
                # aggiunte allora, e la squadra la sappiamo gia'.
                n_saltati += 1
                nuovi_visti[path] = prec
                if prec[1] and (slug not in squadra_per_slug
                                or prec[2] > squadra_per_slug[slug][1]):
                    squadra_per_slug[slug] = (prec[1], prec[2])
                continue
            try:
                d = json.load(open(path, encoding='utf-8'))
            except Exception:
                continue
            n_letti += 1
            conta = collections.Counter()
            for v in (d or {}).values():
                g = (v or {}).get('anyGame') or {}
                gid = g.get('id')
                data = (g.get('date') or '')[:10]
                casa = (g.get('homeTeam') or {}).get('slug')
                fuori = (g.get('awayTeam') or {}).get('slug')
                if casa:
                    conta[casa] += 1
                if fuori:
                    conta[fuori] += 1
                if (not gid or not data or data <= ultima_data
                        or g.get('statusTyped') != 'played'):
                    continue
                candidate[gid] = {'date': data, 'home': casa, 'away': fuori}
            squadra = max(conta, key=conta.get) if conta else None
            n_part = sum(conta.values())
            nuovi_visti[path] = [dim, squadra, n_part]
            if squadra and (slug not in squadra_per_slug
                            or n_part > squadra_per_slug[slug][1]):
                squadra_per_slug[slug] = (squadra, n_part)

    print(f'cache game-log: {n_letti} file letti, {n_saltati} saltati '
          f'(identici al giro scorso)')
    os.makedirs(os.path.dirname(VISTI), exist_ok=True)
    json.dump({'versione': VISTI_VERSIONE, 'file': nuovi_visti},
              open(VISTI, 'w', encoding='utf-8'))
    return candidate, {s: v[0] for s, v in squadra_per_slug.items()}


def _aggiorna_incrementale():
    """Estende il file della stagione corrente con le partite nuove
    (successive all'ultima data gia' coperta), stesse squadre di sempre.
    Ritorna il path del file (aggiornato o creato)."""
    from analisi_manager.p40_estrai_gol_squadre_crowss import estrai_gol

    f_corrente = _ultimo_file(CORRENTE_GLOB)
    esistenti = json.load(open(f_corrente, encoding='utf-8')) if f_corrente else {}
    ultima_data = max((r['date'] for r in esistenti.values()), default='2025-08-01')
    print(f"file corrente: {f_corrente or '(nessuno, primo run)'}  ultima data coperta: {ultima_data}")

    # UNA passeggiata sola (12/08/2026). Prima erano due sugli stessi 6.432
    # file: squadre_archivio() ne faceva una per ricostruire l'indice da 20 MB
    # di p36, e il ciclo qui sotto un'altra per le partite nuove. Adesso la
    # scansione restituisce entrambe le cose e salta i file non cambiati.
    candidate, squadra_per_slug = _scansiona_cache(ultima_data)

    # Le squadre di riferimento sono quelle dei giocatori dell'archivio, come
    # faceva squadre_archivio(): stesso insieme, ricavato dalla stessa cache.
    giocatori = {r['slug'] for r in json.load(open(POOL_ARCHIVIO, encoding='utf-8'))}
    squadre = {squadra_per_slug[p] for p in giocatori if squadra_per_slug.get(p)}

    nuove = {gid: meta for gid, meta in candidate.items()
             if gid not in esistenti
             and (meta['home'] in squadre or meta['away'] in squadre)}

    print(f"squadre di riferimento: {len(squadre)} (da {len(giocatori)} giocatori d'archivio)")
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
