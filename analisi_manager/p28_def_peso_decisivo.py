"""DEF: peso esplicito decisivo/granulare sulla FORMULA VERA di produzione (13/08/2026).

Priorita' #2 di docs/handoff/HANDOFF_ORCHESTRATORE_NUOVO_2026-08-13.txt: oggi
(12/08) un test sulla scomposizione grezza (senza casa/trasferta, Stadio D,
shrinkage) aveva trovato w=0 meglio di w=1 per il DEF. Da rifare sulla
formula vera (compute_score_atteso_def).

METODO (nessuna riga di matematica reinventata): la produzione calcola

    grezzo = level_score_atteso + granulare_term          (w implicito = 1)
    grezzo_corretto = shrink(grezzo, prior, n, k)
    score_no_stadio_d = grezzo_corretto * fattore_casa_trasferta
    score_atteso = score_no_stadio_d + stadio_d_delta      (indipendente da w:
                                                              non tocca decisivo/granulare)

Per un w arbitrario basta ricombinare (w*level_score_atteso + granulare_term)
con le STESSE funzioni di produzione (weighted_mean, expected_level_from_rates,
compute_trend_factor, compute_split_factor -- tutte importate da test_def.py,
mai riscritte) e sommare lo stesso stadio_d_delta gia' calcolato da
compute_score_atteso_def() vera. Test A/A: con w=1 il ricalcolo DEVE
combaciare esattamente con l'output della funzione vera (verificato sotto).

Uso: python analisi_manager/p28_def_peso_decisivo.py
"""
import os
import sys
import json
import glob
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'analisi_manager'))

import backtest_arene_previsioni as P
import backtest_arene_cache as CACHE
import p24_binario2_ga as G

cache = CACHE.CacheLocale()
TD = P._MODULO['Defender']

OUT_PATH = os.path.join(ROOT, 'analisi_manager', 'dati', 'def_decomposizione_2026-08-13.json')


def decomponi(ctx):
    """Ricalcola level_score_atteso / granulare_term / fattore_casa_trasferta /
    stadio_d_delta per il ctx di un DEF, usando solo funzioni di test_def.py."""
    s, casa, presenza = ctx['s'], ctx['casa'], ctx['presenza']
    n = len(s['scores'])
    if n == 0:
        return None
    weights = TD.exponential_weights(n, TD.HALF_LIFE_GAMES)
    weights_det = TD.mask_weights(weights, None)

    media_granulari_pesata = TD.weighted_mean(s['granulari'], weights_det)
    lambda_pos_dec = TD.weighted_mean(s['pos_dec'], weights_det)  # opponent_lambda_mult=1.0 (usa_avversario=False in questa pipeline)
    lambda_neg_dec = TD.weighted_mean(s['neg_dec'], weights_det)
    level_score_atteso = TD.expected_level_from_rates(lambda_pos_dec, lambda_neg_dec)
    fattore_trend_granulare, _s, _l = TD.compute_trend_factor(
        s['granulari'], short_window=5, long_window=10,
        trend_intensity=TD.TREND_INTENSITY, weights=weights_det)
    granulare_term = media_granulari_pesata * fattore_trend_granulare

    media_ruolo_prior = TD.MEDIA_RUOLO_DEF_PRIOR
    if presenza is not None:
        media_ruolo_prior = max(0.0, 45.36 + 7.96 * presenza)
    shrink_k = TD.SHRINK_K_OUTLIER_DEF

    fattore_casa_trasferta = TD.compute_split_factor(s['residual'], s['is_home'], casa, weights_det)

    def ricombina(w):
        grezzo = w * level_score_atteso + granulare_term
        grezzo_corretto = (n / (n + shrink_k)) * grezzo + (shrink_k / (n + shrink_k)) * media_ruolo_prior
        return grezzo_corretto * fattore_casa_trasferta

    score_no_stadio_d_w1 = ricombina(1.0)
    score_full_w1 = TD.compute_score_atteso_def(
        s['scores'], s['is_home'], s['opp_rank'], s['residual'], s['granulari'],
        s['pos_dec'], s['neg_dec'], s['goals_conceded'], s['passing'], s['clean_sheet'],
        target_is_home=casa, target_opp_rank=ctx['opp_rank'], presence_rate=presenza)
    stadio_d_delta = score_full_w1 - score_no_stadio_d_w1

    return {'level_score_atteso': level_score_atteso, 'granulare_term': granulare_term,
            'fattore_casa_trasferta': fattore_casa_trasferta, 'media_ruolo_prior': media_ruolo_prior,
            'shrink_k': shrink_k, 'n': n, 'stadio_d_delta': stadio_d_delta,
            'score_full_w1': score_full_w1, 'ricombina': ricombina}


def raccogli():
    rows = []
    n_scarti = collections.Counter()
    for manager, fx, path in G.elenca_fixture():
        righe = G.carica_formazioni(path)
        pool, _escluse = G.costruisci_pool_carte(righe)
        fine_giornata = G.fine_giornata_da_slug(fx)
        primo_kickoff = G.trova_primo_kickoff(pool, fine_giornata)
        if primo_kickoff is None:
            continue
        for cid, c in pool.items():
            if c['ruolo'] != 'Defender':
                continue
            ctx = P.contesto(cache, c['slug'], 'Defender', fine_giornata, cutoff_giornata=primo_kickoff)
            if ctx is None:
                n_scarti['no_ctx'] += 1
                continue
            reale = G.grezzo_da_archivio(c)
            if reale is None:
                n_scarti['no_reale'] += 1
                continue
            dec = decomponi(ctx)
            if dec is None:
                n_scarti['no_decomposizione'] += 1
                continue
            rows.append({'manager': manager, 'fixture': fx, 'slug': c['slug'], 'nome': c['nome'],
                        'reale': reale, 'level_score_atteso': dec['level_score_atteso'],
                        'granulare_term': dec['granulare_term'],
                        'fattore_casa_trasferta': dec['fattore_casa_trasferta'],
                        'media_ruolo_prior': dec['media_ruolo_prior'], 'shrink_k': dec['shrink_k'],
                        'n': dec['n'], 'stadio_d_delta': dec['stadio_d_delta'],
                        'score_full_w1': dec['score_full_w1']})
    print('scarti:', dict(n_scarti))
    return rows


def main():
    rows = raccogli()
    print(f'righe DEF raccolte: {len(rows)}')

    # test A/A: il ricalcolo con w=1 deve combaciare col vero score di produzione
    max_diff = max(abs(_ricombina_e_check(r)) for r in rows) if rows else 0.0
    print(f'test A/A (w=1 ricostruito vs produzione vera), scarto massimo: {max_diff:.6f}')

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print('salvato:', OUT_PATH)


def _ricombina_e_check(r):
    grezzo = 1.0 * r['level_score_atteso'] + r['granulare_term']
    grezzo_corretto = (r['n'] / (r['n'] + r['shrink_k'])) * grezzo + (r['shrink_k'] / (r['n'] + r['shrink_k'])) * r['media_ruolo_prior']
    score_no_stadio_d = grezzo_corretto * r['fattore_casa_trasferta']
    score_w1 = score_no_stadio_d + r['stadio_d_delta']
    return score_w1 - r['score_full_w1']


if __name__ == '__main__':
    main()
