# -*- coding: utf-8 -*-
"""GK_ATT_AVV FUORI CAMPIONE, SENZA ASPETTARE IL 25/08 (13/08/2026).

IL PROBLEMA, come per il voto A-F. La formula "secca" del correttivo
portiere (quanto segna di solito la squadra AVVERSARIA) e' stata scelta fra
5 candidate SUGLI STESSI DATI su cui e' stata poi confermata: campioni
annidati (337->360 GW-manager = +6% di dati nuovi), non repliche
indipendenti. Per questo era stata pre-registrata una ri-misura su GW5/6/7,
"dal 25/08 in poi", con la regola esplicita: se il segno esce negativo si
rispegne GK_ATT_AVV_ENABLED (HANDOFF_UNIFICATO §5.6).

PERCHE' NON SI ASPETTA. Quelle tre giornate non hanno nessuna
giustificazione statistica -- sono semplicemente le tre successive a quando
fu scritta la pre-registrazione, e con ~87 coppie non deciderebbero niente.
L'archivio e' invece stato allargato ALL'INDIETRO (65 manager, 44 giornate,
1.338 unita'): le giornate di febbraio-marzo e i 36 manager nuovi non sono
MAI stati usati per scegliere la formula, quindi valgono come fuori campione
esattamente quanto le giornate future.

COME. Il correttivo e' un termine ADDITIVO sull'atteso calibrato dei soli
portieri (p24_binario2_ga.py:180-186). Le righe del pool si portano dietro
`opp_slug`, quindi in un processo solo si costruiscono le due versioni:
ACCESO = come gira in produzione oggi, SPENTO = stessa riga meno
l'aggiustamento. Nessun doppio import, nessuno stato di modulo da mescolare.

COSA RIPORTA. Il delta G_on - G_off in essenze, su tre campioni:
  - TUTTO l'archivio (contiene anche i dati con cui la formula fu scelta);
  - solo le GIORNATE NUOVE (feb-mar 2026, mai viste);
  - solo i MANAGER NUOVI (mazzi mai visti).
Il numero che decide e' il secondo. Bootstrap ricampionando i MANAGER.

Uso: GK_ATT_AVV_ENABLED=1 python analisi_manager/p63_gk_att_avv_fuoricampo.py
     (serve acceso: e' cosi' che le righe nascono col correttivo dentro)
"""
import os
import sys
import io
import random
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

# le 12 giornate estratte il 13/08, mai usate per scegliere nessuna formula
GIORNATE_NUOVE = {
    'football-20-24-feb-2026', 'football-24-27-feb-2026',
    'football-27-feb-3-mar-2026', 'football-3-6-mar-2026',
    'football-6-10-mar-2026', 'football-10-13-mar-2026',
    'football-13-17-mar-2026', 'football-17-20-mar-2026',
    'football-20-24-mar-2026', 'football-25-27-mar-2026',
    'football-27-31-mar-2026', 'football-31-mar-3-apr-2026',
}
MANAGER_NUOVI = set("""machado1422 tobibins outbackeras ribarros c-e-l-l-o crackito94
stevinhopelainvicta julck29 sport_nft_card
lukap-c6eb0887-dbd4-4d2a-9eef-884e43c92ba9 tunne11 nikito2444 arnilemonade
malone lorc-67 scafc2 barbacco u-piscaturi pitch11 pandito istvan_babos2001
stevekats s-collymore kiko-77
drcastafolte-171cfbf4-8e38-4188-9eb7-113633f3a5d2 pablo0078 xoubapreta pb99
planabcxyz malgalani-acf4029e-859f-4503-8e2e-a3c2e50a90d3 chrifini llooll4412
rez0r1954 toposensacoda stevie_1dah r4ggio""".split())


def boot_per_manager(a, b, n_boot=5000, seed=20260813):
    chiavi = sorted(set(a) & set(b))
    if not chiavi:
        return None
    per_man = collections.defaultdict(list)
    for k in chiavi:
        per_man[k[0]].append(k)
    manager = sorted(per_man)
    rnd = random.Random(seed)
    ds = []
    for _ in range(n_boot):
        tot = 0.0
        for _i in range(len(manager)):
            m = manager[rnd.randrange(len(manager))]
            for k in per_man[m]:
                tot += b[k] - a[k]
        ds.append(tot)
    ds.sort()
    n = len(ds)
    return {'delta': sum(b[k] - a[k] for k in chiavi),
            'lo': ds[int(0.025 * n)], 'hi': ds[int(0.975 * n)],
            'pct': sum(1 for d in ds if d > 0) / n,
            'n': len(chiavi), 'n_man': len(manager),
            'disc': sum(1 for k in chiavi if abs(b[k] - a[k]) > 1e-9)}


def riporta(eti, off, on, filtro=None):
    a = {k: v for k, v in off.items() if filtro is None or filtro(k)}
    b = {k: v for k, v in on.items() if filtro is None or filtro(k)}
    r = boot_per_manager(a, b)
    if r is None:
        print('%-26s nessuna unita\'' % eti)
        return
    print('%-26s %+9.0f  IC95[%+8.0f;%+8.0f]  pos %5.1f%%  n=%4d (%2d man)  cambia in %d'
          % (eti, r['delta'], r['lo'], r['hi'], r['pct'] * 100, r['n'], r['n_man'], r['disc']))
    if r['n']:
        print('%-26s %+.1f essenze per unita\'' % ('', r['delta'] / r['n']))
    return r


def main():
    if not S21.bfg.GK_ATT_AVV_ENABLED:
        print('ERRORE: serve GK_ATT_AVV_ENABLED=1, altrimenti le righe nascono')
        print('gia\' senza correttivo e i due bracci sarebbero identici.')
        return

    fixtures = B2.elenca_fixture()
    lega_di = AG.indice_lega()
    idx_grade, _ = S21.carica_indice_grade()

    off, on = {}, {}
    n_gk = 0
    scarti = []
    for manager, fx, path in fixtures:
        pre = B2.processa_fixture_pass1(manager, fx, path, lega_di, idx_grade)
        if pre is None:
            continue
        righe_on = [dict(r) for r in pre['pool_rows']]
        righe_off = []
        for r in pre['pool_rows']:
            r2 = dict(r)
            if r2['codice'] == 'GK':
                adj = S21.bfg.gk_att_avv_aggiustamento(r2.get('opp_slug'))
                if adj:
                    n_gk += 1
                    scarti.append(adj)
                r2['_cal'] = round(r2['_cal'] - adj, 1)
            righe_off.append(r2)
        for rows, dove in ((righe_off, off), (righe_on, on)):
            S21.applica_gruppi_grade(rows, modo='lega_ruolo')
            esito = B2.processa_fixture_pass2({
                'manager': pre['manager'], 'fixture': pre['fixture'],
                'pool_size': pre['pool_size'], 'escluse_dnp': pre['escluse_dnp'],
                'primo_kickoff': pre['primo_kickoff'], 'pool_rows': rows})
            dove[(pre['manager'], pre['fixture'])] = \
                sum(x['netto_stimato'] for x in esito['ris_G'])

    print('=' * 100)
    print('GK_ATT_AVV -- correttivo acceso contro spento, braccio G (produzione)')
    print('portieri toccati dal correttivo: %d  |  aggiustamento medio %+.2f, '
          'min %+.2f, max %+.2f'
          % (n_gk, sum(scarti) / len(scarti) if scarti else 0.0,
             min(scarti) if scarti else 0.0, max(scarti) if scarti else 0.0))
    print('=' * 100)
    if n_gk == 0:
        print('IL CORRETTIVO NON TOCCA NESSUNA RIGA: il test sarebbe nullo per')
        print('costruzione. Controlla la tabella gk_attacco_avversario.json.')
        return

    riporta('TUTTO l\'archivio', off, on)
    print()
    print('--- fuori campione vero (mai usato per scegliere la formula) ---')
    riporta('solo GIORNATE nuove', off, on, lambda k: k[1] in GIORNATE_NUOVE)
    riporta('solo MANAGER nuovi', off, on, lambda k: k[0] in MANAGER_NUOVI)
    riporta('nuove O manager nuovi', off, on,
            lambda k: k[1] in GIORNATE_NUOVE or k[0] in MANAGER_NUOVI)
    print()
    print('REGOLA SCRITTA PRIMA (riassunto §5.6): se il segno esce NEGATIVO')
    print('sul fuori campione, GK_ATT_AVV_ENABLED va rispento di default.')
    print('Atteso dichiarato allora: ~+15 essenze per unita\'.')


if __name__ == '__main__':
    main()
