"""Test locale, ZERO rete: verifica che il fix 'storia completa' faccia quello
che promette e non regredisca i casi normali.

Monkeypatcha fetch_game_scores (l'unico punto che tocca la rete) e controlla
quante partite vengono RICHIESTE nei vari scenari.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

REPO = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
MOD = os.path.join(REPO, 'formazione_mls', 'predict', 'test_mid.py')

spec = importlib.util.spec_from_file_location('tm', MOD)
tm = importlib.util.module_from_spec(spec)
sys.modules['tm'] = tm
spec.loader.exec_module(tm)

tmp = tempfile.mkdtemp(prefix='glcache_')
tm.GAME_LOG_CACHE_DIR = tmp

RICHIESTE = []


def finto_fetch(n_disponibili, fine_pulita=True):
    """Simula fetch_game_scores: torna le n_disponibili partite PIU' RECENTI,
    fino a quante ne vengono richieste. Le partite nuove hanno id nuovi e
    stanno in cima, come nell'API vera (ordine dal piu' recente)."""
    def _f(slug, fetch_count):
        RICHIESTE.append(fetch_count)
        n = min(fetch_count, n_disponibili)
        tm.FINE_STORIA_RAGGIUNTA = bool(fine_pulita and n < fetch_count)
        tm.PAGINAZIONE_INTERROTTA = bool(not fine_pulita and n < fetch_count)
        # id decrescenti: g<n_disponibili-1> e' la piu' recente
        nodi = [{'id': f'g{n_disponibili - 1 - i}', 'scoreStatus': 'FINAL', 'score': 40,
                 'anyGame': {'date': f'2026-0{1 + i % 8}-0{1 + i % 9}T12:00:00Z'}}
                for i in range(n)]
        return {'data': {'anyPlayer': {'allPlayerGameScores': {'nodes': nodi},
                                       'anyFutureGames': {'nodes': []},
                                       'activeClub': {'slug': 'x'}}}}
    return _f


def esegui(slug, n_disponibili, giri=3, fine_pulita=True):
    tm.fetch_game_scores = finto_fetch(n_disponibili, fine_pulita)
    RICHIESTE.clear()
    for _ in range(giri):
        tm.fetch_game_log_incremental(slug, target_window_size=tm.WINDOW_SIZE)
    return list(RICHIESTE)


def esito(nome, ottenuto, atteso):
    ok = ottenuto == atteso
    print(('  OK  ' if ok else '  FALLITO ') + nome)
    print(f'        partite richieste per run: {ottenuto}   (atteso {atteso})')
    return ok


print('WINDOW_SIZE =', tm.WINDOW_SIZE, ' PAGINA_GAME_LOG =', tm.PAGINA_GAME_LOG,
      ' GAME_LOG_REFRESH_COUNT =', tm.GAME_LOG_REFRESH_COUNT)
print()
tutti = []

print('1) giocatore con POCA storia (21 partite in tutto) -- e\' il caso da 45%')
tutti.append(esito('prima run chiede 60, le due dopo una pagina sola',
                   esegui('poco-storico', 21), [60, 10, 10]))

print('2) giocatore con storia ABBONDANTE (80 partite): nessun cambiamento')
tutti.append(esito('prima run 60, poi refresh leggero come sempre',
                   esegui('molto-storico', 80), [60, 2, 2]))

print("3) paginazione INTERROTTA da un errore: nessun marcatore, di nessun tipo")
tutti.append(esito('resta il fetch ampio a ogni run, come oggi',
                   esegui('rotto', 21, fine_pulita=False), [60, 60, 60]))

print('4) storia completa, poi il giocatore GIOCA partite nuove')
tm.fetch_game_scores = finto_fetch(21)
RICHIESTE.clear()
tm.fetch_game_log_incremental('cresce', target_window_size=tm.WINDOW_SIZE)   # 60 -> marcatore
tm.fetch_game_log_incremental('cresce', target_window_size=tm.WINDOW_SIZE)   # 10, invariato
tm.fetch_game_scores = finto_fetch(26)   # ora ne ha 26: la pagina di controllo ne trova di nuove
tm.fetch_game_log_incremental('cresce', target_window_size=tm.WINDOW_SIZE)   # 10, cache cresce
tm.fetch_game_scores = finto_fetch(26)
tm.fetch_game_log_incremental('cresce', target_window_size=tm.WINDOW_SIZE)   # torna ampio
tutti.append(esito('il marcatore cade e la run dopo ricontrolla tutto',
                   list(RICHIESTE), [60, 10, 10, 60]))

def finto_panchinaro():
    def _f(slug, fetch_count):
        RICHIESTE.append(fetch_count)
        n = min(fetch_count, 80)
        tm.FINE_STORIA_RAGGIUNTA = False      # 80 partite: hasNextPage resta vero
        tm.PAGINAZIONE_INTERROTTA = False
        nodi = [{'id': 'q%d' % (79 - i), 'scoreStatus': 'FINAL' if i < 12 else 'DID_NOT_PLAY',
                 'score': 10, 'anyGame': {'date': '2026-0%d-0%dT12:00:00Z' % (1 + i % 8, 1 + i % 9)}}
                for i in range(n)]
        return {'data': {'anyPlayer': {'allPlayerGameScores': {'nodes': nodi},
                                       'anyFutureGames': {'nodes': []},
                                       'activeClub': {'slug': 'x'}}}}
    return _f

print('6) PANCHINARO: 80 partite in carriera ma solo 12 FINAL (i 380 casi residui)')
tm.fetch_game_scores = finto_panchinaro()
RICHIESTE.clear()
for _ in range(3):
    tm.fetch_game_log_incremental('panchinaro', target_window_size=tm.WINDOW_SIZE)
tutti.append(esito('la storia non finisce mai, ma dalla 3a run il fetch ampio non si rifa\''
                   ' (serve una run in piu\' per accorgersene: alla 1a le 60 partite sono'
                   ' tutte nuove per costruzione)',
                   list(RICHIESTE), [60, 60, 10]))

print('5) il file di metadati NON inquina la cache condivisa')
f = [x for x in os.listdir(tmp) if x.endswith('_gamelog.json')]
m = [x for x in os.listdir(tmp) if x.endswith('.meta.json')]
cache_poco = json.load(open(os.path.join(tmp, 'poco-storico_gamelog.json'), encoding='utf-8'))
ok5 = (all(not x.endswith('_gamelog.json') for x in m)
       and all(isinstance(v, dict) and 'anyGame' in v for v in cache_poco.values()))
print(('  OK  ' if ok5 else '  FALLITO ') + 'i .meta.json non contano come gamelog e la cache resta di sole partite')
print(f'        file _gamelog.json: {len(f)}   file .meta.json: {len(m)}')
print(f'        esempio meta: {open(os.path.join(tmp, "poco-storico_gamelog.meta.json"), encoding="utf-8").read()}')
tutti.append(ok5)

shutil.rmtree(tmp, ignore_errors=True)
print()
print('ESITO:', 'TUTTI PASSATI' if all(tutti) else 'CI SONO FALLIMENTI')
sys.exit(0 if all(tutti) else 1)
