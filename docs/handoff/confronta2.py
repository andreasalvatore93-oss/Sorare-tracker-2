# -*- coding: utf-8 -*-
"""Confronta le carte copiate da Sorare con i giocatori tenuti dal bot.

    python confronta2.py <gk|def|mid|fwd> <file_schermata>

Riconosce i DUE formati con cui l'utente incolla la lista:
  A) blocchi che cominciano con "<Nome> - limited" e finiscono con "NN%"
  B) blocchi in cui il nome sta sulla riga PRIMA del ruolo (DF/CC/ATT) e la
     percentuale due righe dopo:
         Jakub Kiwior
         DF
         +10
         90%
Lo stesso giocatore compare una volta per CARTA posseduta: qui si contano i
GIOCATORI distinti, che e' l'unita' con cui ragiona il bot.
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
# soglia in percentuale: 80 di default, 60 per la lista completa
SOGLIA = int(sys.argv[3]) if len(sys.argv) > 3 else 80
DATA = '2026-08-12'
RUOLI_SORARE = {'POR': 'gk', 'DF': 'def', 'CC': 'mid', 'ATT': 'fwd'}


def normalizza(nome):
    s = unicodedata.normalize('NFKD', nome)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()
    return ' '.join(sorted(s.split()))


# ------------------------------------------------------------ schermata ---
righe = [l.strip() for l in io.open(SCHERMATA, encoding='utf-8').read().split('\n')]
carte = []

# formato A
nome = None
for l in righe:
    m = re.match(r'^(.*?)\s*-\s*limited$', l)
    if m and m.group(1):
        nome = m.group(1).strip()
        continue
    mp = re.match(r'^(\d{2,3})%$', l)
    if mp and nome:
        carte.append((nome, int(mp.group(1))))
        nome = None

# formato B
if not carte:
    for i, l in enumerate(righe):
        if l not in RUOLI_SORARE:
            continue
        # La sigla del ruolo puo' coincidere col codice di una SQUADRA: POR e'
        # sia 'portiere' sia il Porto, e nel blocco di Diogo Costa (Rio Ave -
        # Porto) faceva nascere un portiere fantasma di nome 'RIO'. Qui il nome
        # e' sempre ripetuto due volte prima del ruolo, tranne nel primissimo
        # blocco: si pretende quella ripetizione.
        if i >= 2 and righe[i - 1] != righe[i - 2]:
            continue
        nome = righe[i - 1] if i else ''
        pct = None
        for j in range(i + 1, min(i + 5, len(righe))):
            mp = re.match(r'^(\d{2,3})%$', righe[j])
            if mp:
                pct = int(mp.group(1))
                break
        if nome and nome not in RUOLI_SORARE and pct is not None:
            carte.append((nome, pct))

sopra = [(n, p) for n, p in carte if p >= SOGLIA]
sorare = {}
for n, p in sopra:
    sorare.setdefault(normalizza(n), (n, p))

# ---------------------------------------------------------------- il bot ---
bot = {}
for p in sorted(glob.glob('formazione_*/output/*_%s_discovery/player_slugs.json' % RUOLO)):
    p = p.replace(os.sep, '/')
    lega = p.split('/')[0][len('formazione_'):]
    slugs = json.load(open(p, encoding='utf-8'))
    if not slugs:
        continue
    if not glob.glob('formazione_%s/output/%s_%s_all/prediction_*_%s_2*.txt'
                     % (lega, lega, RUOLO, DATA)):
        continue          # avanzo di run vecchie: campionato che oggi non gioca
    nomi = {}
    fn = p.replace('player_slugs.json', 'player_names.json')
    if os.path.exists(fn):
        nomi = json.load(open(fn, encoding='utf-8'))
    for s in slugs:
        bot[normalizza(nomi.get(s, s.replace('-', ' ')))] = (nomi.get(s, s), lega)

print('=' * 74)
print('RUOLO %s' % RUOLO.upper())
print('  schermata: %d carte, %d sopra %d%%  ->  %d giocatori distinti'
      % (len(carte), len(sopra), SOGLIA, len(sorare)))
print('  bot      : %d giocatori tenuti' % len(bot))

mancanti = sorted(set(sorare) - set(bot))
extra = sorted(set(bot) - set(sorare))

print('')
print('  SULLA SCHERMATA MA NON NEL BOT: %d   <-- buchi veri' % len(mancanti))
for k in mancanti:
    n, p = sorare[k]
    print('     %-34s %d%%' % (n, p))
print('')
print('  NEL BOT MA NON SULLA SCHERMATA: %d' % len(extra))
for k in extra:
    n, lega = bot[k]
    print('     %-34s (%s)' % (n, lega))
