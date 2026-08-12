# -*- coding: utf-8 -*-
"""Non solo CHI, ma QUANTE carte: il bot conta bene i doppioni?

Il numero di copie non e' un dettaglio: e' quante volte quel giocatore puo'
essere schierato in arene diverse nella stessa giornata. Se il bot ne conta
una in meno, una formazione resta senza portiere.

Il bot tiene il conto in player_card_counts.json come in_season + classic.
La schermata Sorare ha un blocco per ogni carta posseduta.

    python confronta_carte.py <gk|def|mid|fwd> <file_schermata> [soglia]
"""
import glob
import io
import json
import os
import re
import sys
import unicodedata

RUOLO = sys.argv[1]
SCHERMATA = sys.argv[2]
SOGLIA = int(sys.argv[3]) if len(sys.argv) > 3 else 60
DATA = '2026-08-12'
RUOLI_SORARE = {'POR', 'DF', 'CC', 'ATT'}


def normalizza(nome):
    s = unicodedata.normalize('NFKD', nome)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()
    return ' '.join(sorted(s.split()))


# ------------------------------------------------- carte sulla schermata ---
righe = [l.strip() for l in io.open(SCHERMATA, encoding='utf-8').read().split('\n')]
carte = []
nome = None
for l in righe:                                   # formato "<Nome> - limited"
    m = re.match(r'^(.*?)\s*-\s*limited$', l)
    if m and m.group(1):
        nome = m.group(1).strip()
        continue
    mp = re.match(r'^(\d{2,3})%$', l)
    if mp and nome:
        carte.append((nome, int(mp.group(1))))
        nome = None
if not carte:                                     # formato "nome / RUOLO / .. / NN%"
    for i, l in enumerate(righe):
        if l not in RUOLI_SORARE or not i:
            continue
        # La sigla del ruolo puo' coincidere col codice di una SQUADRA:
        # POR e' sia 'portiere' sia il Porto, e nel blocco di Diogo Costa
        # (Rio Ave - Porto) faceva nascere un portiere fantasma di nome
        # 'RIO'. Qui il nome e' sempre ripetuto due volte prima del ruolo,
        # tranne nel primissimo blocco: si pretende quella ripetizione.
        if i >= 2 and righe[i - 1] != righe[i - 2]:
            continue
        pct = None
        for j in range(i + 1, min(i + 5, len(righe))):
            mp = re.match(r'^(\d{2,3})%$', righe[j])
            if mp:
                pct = int(mp.group(1))
                break
        if pct is not None:
            carte.append((righe[i - 1], pct))

conta_sorare = {}
for n, p in carte:
    if p >= SOGLIA:
        k = normalizza(n)
        conta_sorare[k] = conta_sorare.get(k, 0) + 1

# ----------------------------------------------------- carte viste dal bot ---
conta_bot, dove = {}, {}
for p in sorted(glob.glob('formazione_*/output/*_%s_discovery/player_card_counts.json' % RUOLO)):
    p = p.replace(os.sep, '/')
    lega = p.split('/')[0][len('formazione_'):]
    if not glob.glob('formazione_%s/output/%s_%s_all/prediction_*_%s_2*.txt'
                     % (lega, lega, RUOLO, DATA)):
        continue
    nomi = {}
    fn = p.replace('player_card_counts.json', 'player_names.json')
    if os.path.exists(fn):
        nomi = json.load(open(fn, encoding='utf-8'))
    for slug, v in json.load(open(p, encoding='utf-8')).items():
        k = normalizza(nomi.get(slug, slug.replace('-', ' ')))
        conta_bot[k] = conta_bot.get(k, 0) + (v.get('in_season', 0) + v.get('classic', 0))
        dove[k] = (nomi.get(slug, slug), lega)

tot_s = sum(conta_sorare.values())
tot_b = sum(conta_bot.get(k, 0) for k in conta_sorare)
print('=' * 74)
print('RUOLO %s -- CONTEGGIO CARTE (soglia %d%%)' % (RUOLO.upper(), SOGLIA))
print('  carte sulla schermata : %d  su %d giocatori' % (tot_s, len(conta_sorare)))
print('  stesse carte per il bot: %d' % tot_b)
print('')

diff = []
for k, n in sorted(conta_sorare.items()):
    b = conta_bot.get(k)
    if b is None:
        diff.append((dove.get(k, (k, '?'))[0], n, 'assente'))
    elif b != n:
        diff.append((dove[k][0], n, b))

if not diff:
    print('  NESSUNA DIFFERENZA: per ogni giocatore il bot conta le stesse copie.')
else:
    print('  DIFFERENZE (%d giocatori):' % len(diff))
    print('    %-34s %8s %8s' % ('giocatore', 'Sorare', 'bot'))
    for n, s, b in diff:
        print('    %-34s %8d %8s' % (n, s, b))
