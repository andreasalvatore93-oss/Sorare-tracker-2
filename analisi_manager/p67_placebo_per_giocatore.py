# -*- coding: utf-8 -*-
"""IL VOTO GIUDICA IL GIOCATORE O LA PARTITA? (13/08/2026) -- voce 6b

LA DOMANDA, mai posta finora. Tutti i placebo fatti su G rimescolano il
grade FRA GIOCATORI, e rispondono a "il voto porta informazione?" (si':
p<=0,048, §8bis-bis). Questo rimescola il grade **fra le giornate dello
STESSO giocatore**, e risponde a una cosa diversa:

  - se il voto dice "QUESTO GIOCATORE E' FORTE", allora rimescolarlo fra le
    sue giornate cambia poco: ogni giocatore si tiene i suoi voti, solo in
    ordine diverso. Il guadagno sopravvive. Ma allora il voto e' in gran
    parte ridondante: la bravura del giocatore il modello ce l'ha gia' nello
    storico.
  - se il voto dice "QUESTA PARTITA ANDRA' BENE", rimescolarlo fra le
    giornate distrugge il segnale e il guadagno crolla verso il braccio
    senza voto. Allora il voto porta informazione NUOVA, per-partita, che il
    modello non ha da nessun'altra parte.

Serve anche a decidere la voce 14 (tabella fissa per lettera): se il voto e'
un giudizio sul giocatore, una tabella fissa non ha senso di esistere; se e'
sulla singola partita, ne ha eccome.

COME. Il grade e' agganciato alla coppia (slug, giornata). Si costruisce la
mappa vera, poi per OGNI giocatore si permutano i suoi voti fra le sue
giornate, e si rigioca il braccio G. Il pool, gli attesi e le carte restano
identici: cambia solo quale voto cade su quale giornata.

COSTO. `processa_fixture_pass1` (il calcolo degli attesi dalla cache) NON
dipende dal voto e si fa UNA VOLTA SOLA; ogni permutazione rigioca solo
l'applicazione del grade e la scelta delle arene.

Uso: python analisi_manager/p67_placebo_per_giocatore.py [--permutazioni 10]
"""
import os
import sys
import io
import random
import argparse
import collections

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import p12_backtest_formazione_grade as S21  # noqa: E402
import analizza_gw as AG  # noqa: E402
import p24_binario2_ga as B2  # noqa: E402


def gioca(pre_ok, gradi_per_riga=None):
    """Netto totale del braccio G (e di A, che non dipende dal voto).

    gradi_per_riga: None = voti veri. Altrimenti dict (slug, fixture) -> voto
    da sostituire prima di applicare il gruppo."""
    tot_g = tot_a = 0.0
    for pre in pre_ok:
        rows = []
        for r in pre['pool_rows']:
            r2 = dict(r)
            if gradi_per_riga is not None:
                r2['_grade'] = gradi_per_riga.get((r2['slug'], pre['fixture']))
            rows.append(r2)
        S21.applica_gruppi_grade(rows, modo='lega_ruolo')
        esito = B2.processa_fixture_pass2({
            'manager': pre['manager'], 'fixture': pre['fixture'],
            'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
            'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows})
        tot_g += sum(x['netto_stimato'] for x in esito['ris_G'])
        tot_a += sum(x['netto_stimato'] for x in esito['ris_A'])
    return tot_g, tot_a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--permutazioni', type=int, default=10)
    args = ap.parse_args()

    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()
    pre_ok = []
    for manager, fx, path in B2.elenca_fixture():
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is not None:
            pre_ok.append(pre)
    print('unita\' manager-giornata: %d  manager: %d'
          % (len(pre_ok), len(set(p['manager'] for p in pre_ok))))

    # mappa vera (slug, fixture) -> voto, e le giornate di ogni giocatore
    veri = {}
    giornate = collections.defaultdict(list)
    for pre in pre_ok:
        for r in pre['pool_rows']:
            k = (r['slug'], pre['fixture'])
            if k not in veri:
                veri[k] = r.get('_grade')
                giornate[r['slug']].append(pre['fixture'])
    permutabili = {s: fs for s, fs in giornate.items() if len(fs) >= 2}
    con_voto = sum(1 for v in veri.values() if v is not None)
    print('coppie (giocatore, giornata): %d  di cui col voto: %d (%.0f%%)'
          % (len(veri), con_voto, 100.0 * con_voto / max(1, len(veri))))
    print('giocatori con almeno 2 giornate (permutabili): %d su %d'
          % (len(permutabili), len(giornate)))
    if len(permutabili) < 50:
        print('troppo pochi giocatori con piu\' giornate: test nullo.')
        return

    g_vero, a_vero = gioca(pre_ok)
    print()
    print('BRACCIO A (senza voto, non dipende dal placebo): %+.0f' % a_vero)
    print('BRACCIO G, voti VERI:                            %+.0f' % g_vero)
    print('guadagno del voto (G - A):                       %+.0f' % (g_vero - a_vero))
    print()
    print('placebo: i voti di ogni giocatore rimescolati fra le SUE giornate')
    rnd = random.Random(20260813)
    risultati = []
    for i in range(args.permutazioni):
        finti = dict(veri)
        for slug, fs in permutabili.items():
            voti = [veri[(slug, f)] for f in fs]
            rnd.shuffle(voti)
            for f, v in zip(fs, voti):
                finti[(slug, f)] = v
        g, _a = gioca(pre_ok, finti)
        risultati.append(g)
        print('  permutazione %2d/%d: G = %+9.0f   (guadagno %+8.0f, %.0f%% del vero)'
              % (i + 1, args.permutazioni, g, g - a_vero,
                 100.0 * (g - a_vero) / max(1e-9, g_vero - a_vero)))

    risultati.sort()
    n = len(risultati)
    mediana = risultati[n // 2]
    quota = 100.0 * (mediana - a_vero) / max(1e-9, g_vero - a_vero)
    print()
    print('mediana dei placebo: %+.0f  -> guadagno %+.0f, cioe\' il %.0f%% di quello vero'
          % (mediana, mediana - a_vero, quota))
    print('placebo che arrivano o superano il vero: %d su %d'
          % (sum(1 for r in risultati if r >= g_vero), n))
    print()
    print('COME SI LEGGE')
    print('  quota vicina al 100%%: il voto dice soprattutto "questo giocatore')
    print('    e\' forte" -- informazione che il modello ha gia\' nello storico,')
    print('    e la tabella fissa per lettera (voce 14) non ha senso.')
    print('  quota vicina a 0%%: il voto dice "questa partita andra\' bene",')
    print('    informazione NUOVA per-partita: la tabella fissa ha senso e il')
    print('    filone merita di continuare.')


if __name__ == '__main__':
    main()
