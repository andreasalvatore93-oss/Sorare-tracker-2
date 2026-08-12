# -*- coding: utf-8 -*-
"""Toglie i file di output doppi: stessa cosa, stesso giorno, run diverse.

## Perche'

Ogni run del generatore scrive file col timestamp nel nome e non ne cancella
mai nessuno. Lanciare piu' run nella stessa giornata -- normale quando si
prova un parametro, e otto di fila il 12/08/2026 per misurare la velocita' --
lascia quindi N copie dello stesso lavoro.

Non e' solo disordine: ogni job della pipeline, su GitHub e sui runner di
casa, deve materializzare TUTTI i file del repo prima di cominciare a
lavorare. Misurato il 12/08: 75.449 file tracciati, di cui 23.666 predizioni
doppie e 11.422 consigli quasi tutti doppi.

## Perche' si puo' fare senza perdere niente

Chi legge questi file prende SEMPRE l'ultimo:
  - build_consiglio*.py, best_five.py -> sorted(glob)[-1]
  - build_formazione_globale.py       -> latest_consiglio(out_dir)
  - le analisi (p21, diagnosi_buco_grade) -> "il piu' recente"
  - aggiorna_grade_scala_produzione.py legge tutti i consigli ma deduplica
    gia' per (lega, codice, slug, kickoff): le copie non aggiungono righe.
L'analisi storica dell'errore del modello NON usa questi file:
errore_modello_storico.py e confronta_previsioni_giornata.py leggono
prediction_log.json, che e' un aggregato a parte e qui non si tocca.

Restando l'ultimo di OGNI GIORNO si conserva comunque una fotografia
giornaliera, che e' piu' di quanto serva a chiunque legga oggi.

## Cosa NON tocca

  - prediction_log.json e prediction_log_resolved.json (aggregati storici)
  - prediction_all_*.txt (riepiloghi di lega, non per giocatore)
  - le cache, i file di discovery, gli HTML, tutto il resto

## Uso

    python pulisci_predizioni_doppie.py            # dice solo cosa farebbe
    python pulisci_predizioni_doppie.py --esegui   # cancella davvero

Gira anche da solo a fine run (workflow formazione_giornata.yml, job
salva_output) proprio per non far ricrescere il repo.
"""
import collections
import glob
import os
import re
import sys

# Famiglie di file che si accumulano. Per ognuna: come si riconosce il nome e
# che cosa identifica "la stessa cosa" (oltre alla cartella e al giorno).
FAMIGLIE = (
    # prediction_<slug>_<data>_<ora>.txt -> stesso giocatore, stesso giorno
    ('predizioni', re.compile(
        r'^prediction_(?P<chiave>.+)_(?P<data>\d{4}-\d{2}-\d{2})_(?P<ora>\d+)\.txt$')),
    # consiglio_<data>_<ora>.txt -> stessa cartella lega/ruolo, stesso giorno
    ('consigli', re.compile(
        r'^consiglio_(?P<data>\d{4}-\d{2}-\d{2})_(?P<ora>\d+)\.txt$')),
    # ERRORE_<slug>_<data>_<ora>.txt -> stesso giocatore, stesso giorno
    ('errori', re.compile(
        r'^ERRORE_(?P<chiave>.+)_(?P<data>\d{4}-\d{2}-\d{2})_(?P<ora>\d+)\.txt$')),
)

# Riepiloghi di lega: non sono doppioni per-giocatore, si lasciano stare.
SALTA = re.compile(r'^prediction_all(_|$)')


def raccogli():
    """{(famiglia, cartella, chiave, giorno): [(ora, path), ...]}"""
    gruppi = collections.defaultdict(list)
    for path in glob.glob('formazione_*/output/**/*.txt', recursive=True):
        path = path.replace(os.sep, '/')
        cartella, nome = path.rsplit('/', 1)
        if SALTA.match(nome):
            continue
        for fam, rx in FAMIGLIE:
            m = rx.match(nome)
            if not m:
                continue
            chiave = m.groupdict().get('chiave', '')
            gruppi[(fam, cartella, chiave, m.group('data'))].append(
                (m.group('ora'), path))
            break
    return gruppi


def main():
    esegui = '--esegui' in sys.argv
    gruppi = raccogli()

    da_togliere = []
    per_fam = collections.defaultdict(lambda: [0, 0, 0])   # tenuti, tolti, byte
    for (fam, _c, _k, _g), voci in gruppi.items():
        voci.sort()                       # l'ora e' zero-padded: ordine giusto
        per_fam[fam][0] += 1
        for _ora, p in voci[:-1]:         # tutti tranne l'ultimo del giorno
            da_togliere.append(p)
            per_fam[fam][1] += 1
            try:
                per_fam[fam][2] += os.path.getsize(p)
            except OSError:
                pass

    print('%-14s %10s %10s %9s' % ('famiglia', 'tenuti', 'da togliere', 'MB'))
    print('-' * 46)
    for fam in ('predizioni', 'consigli', 'errori'):
        t, x, b = per_fam[fam]
        print('%-14s %10d %10d %9.1f' % (fam, t, x, b / 1e6))
    print('-' * 46)
    tot_t = sum(v[0] for v in per_fam.values())
    tot_x = sum(v[1] for v in per_fam.values())
    tot_b = sum(v[2] for v in per_fam.values())
    print('%-14s %10d %10d %9.1f' % ('TOTALE', tot_t, tot_x, tot_b / 1e6))

    if not da_togliere:
        print('')
        print('Niente da togliere: nessun doppione.')
        return 0

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
    return 0


if __name__ == '__main__':
    sys.exit(main())
