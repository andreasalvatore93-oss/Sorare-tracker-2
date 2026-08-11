"""Costruisce la tabella squadra -> forza d'attacco media (gol fatti storici),
usata dal correttivo GK_ATT_AVV in build_formazione_globale.py (flag
GK_ATT_AVV_ENABLED, spento di default).

Segnale misurato e validato: analisi_manager/p42_gk_dispersione_tenuta_oos.py
(n=716, corr att_media/reale GK -0,091 con segno "piu' l'avversario segna,
meno rende il portiere") e analisi_manager/p44_gk_tenuta_2024_25.py (n=1896,
blocco temporale indipendente, IC esclude lo zero). Pendenza di regressione
pooled (n=2612, entrambi i blocchi): k=-4.26, intercetta ~54.5, media globale
att_media 1.400, sd 0.401 -- vedi docs/handoff/RISPOSTA_OPUS_CORRELAZIONI_
2026-08-13.txt §11 per il dettaglio dei test.

Qui NON si rifà la misura: si aggiorna solo la tabella dei valori correnti
per squadra (media di TUTTI i gol fatti disponibili in cache/estrazioni,
nessun leakage: e' storia, si usa per predire il futuro).

Uso: python generatore_formazioni/dati/aggiorna_gk_attacco_avversario.py
Legge: analisi_manager/dati/gol_squadre_archivio_2025-26_*.json,
       analisi_manager/dati/gol_squadre_archivio_2023_25_*.json
Produce: generatore_formazioni/dati/gk_attacco_avversario.json
"""
import os
import sys
import json
import glob
import collections
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)

GOL_FILES = sorted(glob.glob('analisi_manager/dati/gol_squadre_archivio_2025-26_*.json')) + \
            sorted(glob.glob('analisi_manager/dati/gol_squadre_archivio_2023_25_*.json'))
OUT = os.path.join('generatore_formazioni', 'dati', 'gk_attacco_avversario.json')
MIN_STORICO = 4


def main():
    fatti = collections.defaultdict(list)
    n_partite = 0
    for gf in GOL_FILES:
        gol = json.load(open(gf, encoding='utf-8'))
        for g in gol.values():
            h, a = g.get('home'), g.get('away')
            hg, ag = g.get('home_goals'), g.get('away_goals')
            if hg is None or ag is None or not h or not a:
                continue
            fatti[h].append(hg)
            fatti[a].append(ag)
            n_partite += 1
    print(f"file usati: {GOL_FILES}")
    print(f"partite totali: {n_partite}  squadre: {len(fatti)}")

    tabella = {}
    for sq, gols in fatti.items():
        if len(gols) < MIN_STORICO:
            continue
        tabella[sq] = {'att_medio': round(sum(gols) / len(gols), 3), 'n_partite': len(gols)}
    print(f"squadre con storico >= {MIN_STORICO} partite: {len(tabella)}")

    tutti = [v['att_medio'] for v in tabella.values()]
    print(f"media att_medio fra le squadre: {sum(tutti)/len(tutti):.3f}")

    out_obj = {
        '_generato': datetime.date.today().isoformat(),
        '_min_storico': MIN_STORICO,
        '_fonte': GOL_FILES,
        'squadre': tabella,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out_obj, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"salvato: {OUT}")


if __name__ == '__main__':
    main()
