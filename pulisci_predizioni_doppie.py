# -*- coding: utf-8 -*-
"""Toglie le predizioni doppie: stesso giocatore, stesso giorno, run diverse.

## Perche'

Ogni run del generatore scrive un file prediction_<slug>_<data>_<ora>.txt per
ogni giocatore, e non ne cancella mai nessuno. Lanciare piu' run nella stessa
giornata -- cosa normale quando si prova un parametro, e normalissima il
12/08/2026 quando se ne sono fatte otto per misurare la velocita' -- lascia
quindi N copie dello stesso lavoro. Misurato quel giorno: 29.761 file, di cui
23.666 doppioni (80%), 16.816 solo del 12/08 con 1.176 utili.

Non e' solo disordine: ogni job della pipeline, su GitHub e in casa, deve
materializzare tutti i file del repo prima di cominciare a lavorare. Un file
su tre e' una copia che nessuno legge.

## Perche' si puo' fare senza perdere niente

Chi legge questi file prende SEMPRE l'ultimo:
  - build_consiglio*.py -> latest_file_for_slug(): sorted(glob)[-1]
  - best_five.py        -> stessa logica
L'analisi storica dell'errore del modello NON li usa: errore_modello_storico.py
e confronta_previsioni_giornata.py leggono prediction_log.json, che e' un
aggregato a parte e qui non si tocca.

Restando l'ultimo di ogni giorno si conserva comunque una fotografia al giorno
per giocatore, che e' piu' di quanto serva a chiunque legga oggi.

## Cosa NON tocca

  - prediction_log.json e prediction_log_resolved.json (aggregati storici)
  - prediction_all_*.txt (riepiloghi di lega, non per giocatore)
  - ERRORE_*.txt, consiglio_*.txt, le cache, tutto il resto

## Uso

    python pulisci_predizioni_doppie.py            # dice solo cosa farebbe
    python pulisci_predizioni_doppie.py --esegui   # cancella davvero
"""
import collections
import glob
import os
import re
import sys

RIGA = re.compile(r'^prediction_(?P<slug>.+)_(?P<data>\d{4}-\d{2}-\d{2})_'
                  r'(?P<ora>\d+)\.txt$')


def raccogli():
    """{(cartella, slug, giorno): [(ora, path), ...]} per i soli file
    per-giocatore."""
    gruppi = collections.defaultdict(list)
    for path in glob.glob('formazione_*/output/*/prediction_*.txt'):
        path = path.replace(os.sep, '/')
        cartella, nome = path.rsplit('/', 1)
        m = RIGA.match(nome)
        if not m:
            continue
        slug = m.group('slug')
        if slug == 'all' or slug.startswith('all_'):
            continue                      # riepiloghi di lega, non doppioni
        gruppi[(cartella, slug, m.group('data'))].append((m.group('ora'), path))
    return gruppi


def main():
    esegui = '--esegui' in sys.argv
    gruppi = raccogli()

    da_togliere, tenuti, byte = [], 0, 0
    for _k, voci in gruppi.items():
        voci.sort()                       # l'ora e' zero-padded: ordine giusto
        tenuti += 1
        for _ora, p in voci[:-1]:         # tutti tranne l'ultimo del giorno
            da_togliere.append(p)
            try:
                byte += os.path.getsize(p)
            except OSError:
                pass

    tot = tenuti + len(da_togliere)
    print('file per-giocatore trovati : %d' % tot)
    print('  tenuti (ultimo del giorno): %d' % tenuti)
    print('  da togliere (doppioni)    : %d  (%.1f MB)' % (len(da_togliere), byte / 1e6))
    if tot:
        print('  cioe\' il %.0f%%' % (100.0 * len(da_togliere) / tot))

    per_giorno = collections.Counter(p.rsplit('_', 2)[-2] for p in da_togliere)
    print('')
    print('  per giorno:')
    for g, n in sorted(per_giorno.items()):
        print('    %s : %5d' % (g, n))

    if not esegui:
        print('')
        print('PROVA A VUOTO: non ho cancellato niente.')
        print('Per farlo davvero: python pulisci_predizioni_doppie.py --esegui')
        return 0

    n = 0
    for p in da_togliere:
        try:
            os.remove(p)
            n += 1
        except OSError as e:
            print('  non cancellato: %s (%s)' % (p, e))
    print('')
    print('cancellati %d file su %d.' % (n, len(da_togliere)))
    print('Sono tracciati da git: il commit li toglie da main e la storia')
    print('resta, quindi si recuperano con un checkout se mai servissero.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
