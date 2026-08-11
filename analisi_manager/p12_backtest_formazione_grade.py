"""Sez.21 -- backtest a livello di FORMAZIONE INTERA sulle arene reali
dell'utente (crowss): produzione attuale (policy A) vs produzione+grade
come riordinamento a valle (policy G), stesso mazzo, stesso knapsack,
stesse arene, walk-forward stretto.

Riusa TUTTA l'infrastruttura gia' validata di P11 (analisi_manager/
p11_confronta.py): p11_pool.json (mazzo ricostruito + score_atteso grezzo +
reale, per ogni giornata reale dell'utente), backtest_arene_economia.py
(soglie/premi/rank VERI delle arene, non stimati), bfg/bff (lo stesso
knapsack di produzione). NON si tocca la formula di score_atteso: si cambia
solo il valore usato per la SELEZIONE (row['atteso'] nel knapsack), i punti
realizzati restano sempre quelli VERI.

Policy G = per ogni (lega,ruolo) dentro una giornata, fra i candidati con
reale disponibile: z-score(atteso_calibrato) + z-score(grade) [grade
mancante -> contributo neutro 0], poi riportato alla scala originale di
score_atteso (moltiplicando per la SD del gruppo) cosi' la competizione fra
RUOLI DIVERSI per lo stesso slot (impossibile con z-score puri, che
cancellano la scala) resta quella di produzione. Algebricamente equivale a:
  atteso_combinato = atteso_calibrato + SD_gruppo(atteso_calibrato) * z(grade)
"""
import os, sys, io, json, math, random, collections, datetime

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SP = os.path.dirname(os.path.abspath(__file__))
ROOT = r'C:\Users\Andrea\Documents\GitHub\Sorare-tracker-2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, SP)

os.environ['GK_TEAM_CS_WEIGHT'] = repr(22.0 / 35.0)
import backtest_arene_produzione as BP
import backtest_arene_economia as E

bfg = BP.bfg
bff = BP.bff

pool_per_gw = json.load(open(os.path.join(SP, 'p11_pool.json'), encoding='utf-8'))
arene_tutte = json.load(open('dati_globali/arene_storico.json', encoding='utf-8'))['arene']
premi_tab = E.tabella_premi(arene_tutte)
arena_per_slug_score = {}
for a in arene_tutte:
    arena_per_slug_score.setdefault((a['slug'], round(a.get('mio_score') or -1, 2)), a)


def costruisci(gw, obiettivo):
    """role_data/pools/card_pool per una giornata (copiato da p11_confronta,
    senza dipendere dal modulo boom/coppie che qui non serve)."""
    pool = [c for c in gw['pool'] if c.get('reale') is not None]
    leghe = sorted(set(c['lega'] for c in pool) | {'senza_lega'})
    role_data = {lg: {r: [] for r in ('GK', 'DEF', 'MID', 'FWD')} for lg in leghe}
    counts = {r: {} for r in ('GK', 'DEF', 'MID', 'FWD')}
    for c in pool:
        cod = c['codice']
        row = {'slug': c['slug'], 'atteso': obiettivo(c), 'low': 0, 'high': 0,
               'team_slug': c['squadra'], 'opponent_team_slug': c['opp_slug'],
               'ordinamento': None, 'kickoff': None, 'opp_factor': None,
               'league': c['lega'], 'role_key': cod, 'carta': c.get('carta'),
               'reale': c['reale'], 'atteso_cal': c['_cal'], '_grade': c.get('_grade')}
        role_data[c['lega']][cod].append(row)
        counts[cod][c['slug']] = {'in_season': c['copie'], 'classic': 0, 'l10': c['l10']}
    for lg in role_data:
        for cod in role_data[lg]:
            role_data[lg][cod].sort(key=lambda r: r['atteso'], reverse=True)
    pools = {lg: {r: bfg._NoFilterPool(r, lg, role_data[lg][r]) for r in ('GK', 'DEF', 'MID', 'FWD')}
             for lg in leghe}
    card_pool = bff.CardPool(counts)
    return role_data, pools, card_pool, leghe


def capitano_atteso(formazione):
    righe = [r for _s, r, _t in formazione]
    fuori = [r for r in righe if r['role_key'] != 'GK']
    gk = [r for r in righe if r['role_key'] == 'GK']
    bo = max(fuori, key=lambda r: r['atteso_cal']) if fuori else None
    bg = max(gk, key=lambda r: r['atteso_cal']) if gk else None
    marg = getattr(bff, 'GK_CAPTAIN_MARGIN', 0)
    if bg and (not bo or bg['atteso_cal'] >= bo['atteso_cal'] + marg):
        return bg
    return bo or bg


def realizzato(formazione, cap_row):
    return sum(r['reale'] for _s, r, _t in formazione) + (1.2 - 1.0) * cap_row['reale']


def esito(slot, punteggio):
    a = arena_per_slug_score.get((slot['slug'], round(slot['mio_score'] or -1, 2)))
    if a is None:
        a = {'punteggi': slot['punteggi'], 'tipo': slot['tipo'],
             'rank_premiato': slot['rank_premiato'], 'premio_essenze': slot['premio_essenze'],
             'costo': slot['costo']}
    rank = E.piazzamento(a, slot['mio_score'], punteggio)
    premio = E.premio(a, rank, premi_tab)
    costo = E.costo(a)
    return rank, premio, costo


def gioca(gw, slots, obiettivo, depleta):
    role_data, pools, card_pool, leghe = costruisci(gw, obiettivo)
    orig = bfg.LEAGUES
    bfg.LEAGUES = tuple(leghe)
    fuori = []
    try:
        for s in slots:
            tipo_bfg = s['tipo_bfg']
            shape = bfg.FORMATION_SHAPES[tipo_bfg]
            pool_league = bfg.POOL_LEAGUE_BY_TYPE[tipo_bfg]
            l10_cap = bfg.L10_CAP_BY_TYPE.get(tipo_bfg)
            stato = bfg._istantanea_pool(card_pool)
            formazione, errore, _ok, _sp = bfg.build_one_lineup_with_growth(
                shape, pool_league, role_data, pools, card_pool, l10_cap,
                apply_stack_guard=False, variance_mode=True,
                apply_positive_synergy=False, strict_gk_anti_synergy=False)
            if errore or not formazione:
                bfg._ripristina_pool(card_pool, stato)
                fuori.append(None)
                continue
            if not depleta:
                bfg._ripristina_pool(card_pool, stato)
            fuori.append(formazione)
    finally:
        bfg.LEAGUES = orig
    return fuori


GRADE_NUM = {'A': 6, 'B': 5, 'C': 4, 'D': 3, 'E': 2, 'F': 1}
random.seed(20260806)

TIPI_CAPPED = {'cap 260', 'cap 220'}


# --------------------------------------------------------- indice grade ---
# BUG SCOPERTO E CORRETTO 07/08/2026 (richiesta esplicita utente, dopo che
# aggiungere piu' dati storici non alzava la copertura 4.6%): il join
# precedente cercava (slug, data_ESATTA_di_fine_fixture). Le fixture durano
# spesso piu' giorni (es. football-1-4-jul-2026), e la partita vera di un
# giocatore cade in un giorno QUALUNQUE della finestra, quasi mai
# esattamente sull'ultimo -- misurato sui dati reali: match esatto 3.4% dei
# candidati, match ammettendo qualunque partita nei GRADE_WINDOW_GIORNI
# prima della fine 56.6%, con gli STESSI dati (nessun dato nuovo servito).
# Ora l'indice e' slug -> lista (data, grade_num) ordinata, e la ricerca
# usa una finestra, non piu' un dict a chiave esatta.
GRADE_WINDOW_GIORNI = 6


def grade_in_finestra(idx_grade, slug, fine_str):
    """Grade piu' vicino (il piu' recente) a fine_str, entro
    GRADE_WINDOW_GIORNI giorni PRIMA (incluso il giorno stesso). None se
    nessuna partita nota in finestra per questo slug."""
    entries = idx_grade.get(slug)
    if not entries:
        return None
    fy, fm, fd = (int(x) for x in fine_str.split('-'))
    fine = datetime.date(fy, fm, fd)
    migliore, migliore_delta = None, None
    for dt, gn in entries:
        yy, mm, dd = (int(x) for x in dt.split('-'))
        delta = (fine - datetime.date(yy, mm, dd)).days
        if 0 <= delta <= GRADE_WINDOW_GIORNI and (migliore_delta is None or delta < migliore_delta):
            migliore, migliore_delta = gn, delta
    return migliore


def carica_indice_grade():
    """slug -> lista ordinata di (data[:10], grade_num), da TUTTE le fonti
    storiche valide (esclude storico_grade_Forward_MIRATO, campione non
    comparabile, sez.20). Lookup con grade_in_finestra(), non piu' chiave
    esatta (vedi nota sopra)."""
    idx = collections.defaultdict(list)
    date_min = None

    def registra(slug, dt, grade):
        nonlocal date_min
        gn = GRADE_NUM.get(grade)
        if gn is None or not dt or not slug:
            return
        idx[slug].append((dt[:10], gn))
        if date_min is None or dt < date_min:
            date_min = dt

    # GK: formato annidato {slug, scores:[{score, anyGame:{date}, projection:{grade}}]}
    d = json.load(open('analisi_manager/p12_r5_gk_ampio.json', encoding='utf-8'))
    for entry in d:
        for s in entry.get('scores') or []:
            proj = s.get('projection') or {}
            registra(entry['slug'], (s.get('anyGame') or {}).get('date'), proj.get('grade'))

    # DEF/MID/FWD: formato piatto (Haiku), FWD quello VALIDO (non _mirato)
    for f in ('analisi_manager/dati/storico_grade_Defender_20260806.json',
             'analisi_manager/dati/storico_grade_Midfielder_20260806.json',
             'analisi_manager/dati/storico_grade_Forward_20260806.json'):
        d = json.load(open(f, encoding='utf-8'))
        for r in d:
            registra(r.get('slug'), r.get('game_date'), r.get('grade'))

    # raccolta MIRATA sui 717 giocatori del mazzo/pool reale crowss (sez.21-22):
    # stesso formato annidato del GK, campo playerGameScores diretto sul giocatore
    d = json.load(open('analisi_manager/dati/storico_grade_crowss_20260806.json', encoding='utf-8'))
    for p in d.get('giocatori') or []:
        for s in p.get('playerGameScores') or []:
            proj = s.get('projection') or {}
            registra(p.get('slug'), (s.get('anyGame') or {}).get('date'), proj.get('grade'))

    # raccolta COMPLETATA 07/08 sul pool crowss (3.745 righe, 249 giocatori,
    # nov25-ago26, richiesta dall'utente per alzare la copertura storica del
    # backtest, che il 07/08 mattina era solo 4.6%): stesso formato piatto
    # di DEF/MID/FWD sopra ({'slug','game_date','grade'}), non annidato come
    # il file 20260806 sopra.
    d = json.load(open('analisi_manager/dati/storico_grade_crowss_20260807.json', encoding='utf-8'))
    for r in d:
        registra(r.get('slug'), r.get('game_date'), r.get('grade'))

    # completamento INCREMENTALE (10/08/2026, completa_grade_mancante.py):
    # file che CRESCE ogni volta che un backtest (es. p23_binario1_mga.py)
    # trova slug/date senza grade e li recupera mirati da Sorare. Stesso
    # formato piatto dei file sopra. Facoltativo: puo' non esistere ancora.
    path_compl = 'analisi_manager/dati/storico_grade_crowss_completamento.json'
    if os.path.exists(path_compl):
        d = json.load(open(path_compl, encoding='utf-8'))
        for r in d:
            registra(r.get('slug'), r.get('game_date'), r.get('grade'))

    for slug in idx:
        idx[slug] = sorted(set(idx[slug]))
    return idx, date_min


def zscore_gruppo(vals):
    n = len(vals)
    if n < 2:
        return [0.0] * n, 0.0, (vals[0] if vals else 0.0)
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    if sd == 0:
        return [0.0] * n, 0.0, m
    return [(v - m) / sd for v in vals], sd, m


def _media_sd(vals):
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    m = sum(vals) / n
    sd = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    return m, sd


def _applica_da_riferimento(target, riferimento):
    """Imposta _zgrade/_combinato su ogni riga di `target`, usando media/sd
    (dell'atteso calibrato '_cal' e del grade '_grade') calcolate su
    `riferimento` -- che puo' coincidere con `target` (gruppo si valuta su
    se stesso, comportamento di sempre) o essere piu' ampio (fallback/
    gruppo esteso, filone 11/08/2026). Stessa formula/soglie di sempre
    (zscore_gruppo): serve almeno 2 grade validi nel riferimento, altrimenti
    zgrade=0 per tutto il target (fallback esplicito, mai un numero
    inventato)."""
    _m_atteso, sd_atteso = _media_sd([m['_cal'] for m in riferimento])
    gp = [m['_grade'] for m in riferimento if m['_grade'] is not None]
    gm, gsd = _media_sd(gp) if len(gp) >= 2 else (0.0, 0.0)
    for m in target:
        if m['_grade'] is not None and len(gp) >= 2 and gsd > 0:
            m['_zgrade'] = (m['_grade'] - gm) / gsd
        else:
            m['_zgrade'] = 0.0
        m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']


def applica_gruppi_grade(rows, modo='lega_ruolo', soglia_piccolo=5, riferimento_esterno=None):
    """Imposta _zgrade/_combinato su ogni riga di `rows` (deve gia' avere
    '_cal', '_grade', 'lega', 'codice'), per TUTTI i ruoli insieme (GK/DEF/
    MID/FWD, non solo GK). Filone 'gruppo grade esteso alla giornata'
    (11/08/2026, richiesta esplicita utente, caso Hugo Lloris: gruppo
    (lega,ruolo) a volte 2-3 carte, troppo piccolo per uno z-score
    affidabile).

    Quattro modalita' (env var GRADE_GROUP_MODE nei chiamanti, default
    'lega_ruolo' = comportamento INVARIATO rispetto a prima di oggi):
      - 'lega_ruolo' (baseline/produzione): gruppo = (lega, ruolo) della
        singola giornata, come sempre. Refactor puro rispetto al codice
        precedente: deve riprodurre risultati bit-per-bit identici (test
        A/A).
      - 'giornata_ruolo' (generale, SEMPRE): gruppo = ruolo, tutte le leghe
        della stessa chiamata (= la giornata) insieme.
      - 'suppletivo' (fallback MIRATO): gruppo nativo (lega, ruolo)
        normalmente; se ha MENO di `soglia_piccolo` membri (pre-registrato
        a 5, prima di vedere risultati: sotto quella soglia lo z-score gia'
        oggi richiede solo >=2 grade validi, troppo poco per una stima
        stabile), le SOLE righe di quel gruppo piccolo usano invece le
        statistiche di tutta la giornata per quel ruolo. I gruppi gia'
        abbastanza grandi restano invariati -- e' un cerotto mirato, non
        una sostituzione generale.
      - 'pool_largo' (11/08/2026 sera, "pool largo del generatore"):
        gruppo = (lega, ruolo) ma pescato da `riferimento_esterno`
        (obbligatorio in questa modalita'), un dict {(lega,ruolo): [righe]}
        costruito dal CHIAMANTE pescando le righe di TUTTI i manager che
        condividono la stessa fixture -- non solo quelle di `rows` (un
        singolo manager). Non si puo' costruire qui dentro: questa funzione
        vede solo il pool di UN manager per volta. Approssima il pool di
        discovery della produzione (molti candidati per lega/ruolo, non
        solo le carte possedute da un manager) riusando dati gia' estratti
        in archivio_ufficiale, zero query nuove."""
    per_lega_ruolo = collections.defaultdict(list)
    per_ruolo = collections.defaultdict(list)
    for r in rows:
        per_lega_ruolo[(r['lega'], r['codice'])].append(r)
        per_ruolo[r['codice']].append(r)

    if modo == 'lega_ruolo':
        for membri in per_lega_ruolo.values():
            _applica_da_riferimento(membri, membri)
    elif modo == 'giornata_ruolo':
        for membri in per_ruolo.values():
            _applica_da_riferimento(membri, membri)
    elif modo == 'suppletivo':
        for (_lega, _ruolo), membri in per_lega_ruolo.items():
            if len(membri) < soglia_piccolo:
                _applica_da_riferimento(membri, per_ruolo[_ruolo])
            else:
                _applica_da_riferimento(membri, membri)
    elif modo == 'pool_largo':
        if riferimento_esterno is None:
            raise ValueError("modo='pool_largo' richiede riferimento_esterno")
        for chiave, membri in per_lega_ruolo.items():
            rif = riferimento_esterno.get(chiave) or membri
            _applica_da_riferimento(membri, rif)
    else:
        raise ValueError(f"GRADE_GROUP_MODE sconosciuto: {modo!r}")


def main():
    idx_grade, data_min = carica_indice_grade()
    _n_coppie = sum(len(v) for v in idx_grade.values())
    print(f'indice grade: {len(idx_grade)} slug, {_n_coppie} coppie (slug,data) da GK/DEF/MID/FWD (FWD valido, non mirato)')
    print(f'prima data con grade disponibile: {data_min}')

    # --- finestra: fixture con cutoff >= prima data col grade ---
    fixtures_ammesse = [fx for fx, gw in pool_per_gw.items() if gw['cutoff'][:10] >= data_min[:10]]
    fixtures_escluse = len(pool_per_gw) - len(fixtures_ammesse)
    n_slot_capped = 0
    for fx in fixtures_ammesse:
        gw = pool_per_gw[fx]
        n_slot_capped += sum(1 for s in gw['slot'] if s['tipo'] in TIPI_CAPPED
                             and s.get('punteggi') and s.get('mio_score') is not None)
    print(f'fixture totali in p11_pool.json: {len(pool_per_gw)}')
    print(f'fixture con cutoff >= {data_min[:10]}: {len(fixtures_ammesse)}  (escluse: {fixtures_escluse})')
    print(f'arene cap 260/220 valide dentro la finestra: {n_slot_capped}')
    print('--- procedo (la finestra include praticamente tutto il campione P11) ---\n')

    righe = []
    saltate_gw = 0
    copertura_candidati = 0
    copertura_con_grade = 0

    for fx, gw in sorted(pool_per_gw.items(), key=lambda kv: kv[1]['cutoff']):
        if fx not in set(fixtures_ammesse):
            continue
        slots = [s for s in gw['slot'] if s['tipo'] in TIPI_CAPPED
                 and s.get('punteggi') and s.get('mio_score') is not None]
        if not slots:
            continue
        pool = [c for c in gw['pool'] if c.get('reale') is not None]
        ruoli = collections.Counter(c['codice'] for c in pool)
        if not all(ruoli[k] >= 1 for k in ('GK', 'DEF', 'MID', 'FWD')):
            saltate_gw += 1
            continue

        data_gw = gw['fine'][:10]
        for c in pool:
            c['_cal'] = bfg.calibra(c['atteso_raw'], c['codice'])
            c['_grade'] = grade_in_finestra(idx_grade, c['slug'], data_gw)
            copertura_candidati += 1
            if c['_grade'] is not None:
                copertura_con_grade += 1

        # z-score(atteso_cal) + z-score(grade), riportato alla scala di atteso_cal,
        # PER GRUPPO (lega, ruolo) -- lo stesso pool su cui il knapsack seleziona
        gruppi = collections.defaultdict(list)
        for c in pool:
            gruppi[(c['lega'], c['codice'])].append(c)
        for (lg, cod), membri in gruppi.items():
            z_atteso, sd_atteso, m_atteso = zscore_gruppo([m['_cal'] for m in membri])
            grade_vals_presenti = [m['_grade'] for m in membri if m['_grade'] is not None]
            if len(grade_vals_presenti) >= 2:
                z_grade_presenti, _, _ = zscore_gruppo(grade_vals_presenti)
                z_grade_iter = iter(z_grade_presenti)
                for m in membri:
                    if m['_grade'] is not None:
                        m['_zgrade'] = next(z_grade_iter)
                    else:
                        m['_zgrade'] = 0.0
            else:
                for m in membri:
                    m['_zgrade'] = 0.0
            for m in membri:
                m['_combinato'] = m['_cal'] + sd_atteso * m['_zgrade']

        slots = sorted(slots, key=lambda s: (s['tipo'], s['slug']))
        fa = gioca(gw, slots, lambda c: c['_cal'], depleta=True)
        fg = gioca(gw, slots, lambda c: c['_combinato'], depleta=True)

        for s, la, lg_ in zip(slots, fa, fg):
            if la is None or lg_ is None:
                continue
            ca = capitano_atteso(la)
            cg = capitano_atteso(lg_)
            pa = realizzato(la, ca)
            pg = realizzato(lg_, cg)
            ra, pra, co = esito(s, pa)
            rg, prg, _ = esito(s, pg)
            ru, pru, _ = esito(s, s['mio_score'])
            sa = set(r['slug'] for _x, r, _t in la)
            sg = set(r['slug'] for _x, r, _t in lg_)
            n_grade_in_g = sum(1 for _x, r, _t in lg_ if r.get('_grade') is not None)
            righe.append({
                'fixture': fx, 'slug': s['slug'], 'tipo': s['tipo'], 'costo': co,
                'A_punti': pa, 'A_rank': ra, 'A_premio': pra,
                'G_punti': pg, 'G_rank': rg, 'G_premio': prg,
                'U_punti': s['mio_score'], 'U_rank': s['mio_rank'], 'U_premio': s['premio_essenze'] or 0,
                'overlap': len(sa & sg), 'identiche': sa == sg,
                'n_grade_in_formazione_G': n_grade_in_g,
            })

    print(f'giornate saltate (pool incompleto): {saltate_gw}')
    print(f'copertura grade nel pool candidati: {copertura_con_grade}/{copertura_candidati} '
          f'({100*copertura_con_grade/copertura_candidati:.1f}%)' if copertura_candidati else '')
    print(f'arene valutate: {len(righe)}  giornate: {len(set(r["fixture"] for r in righe))}')
    print(f'arene dove la formazione G ha ALMENO 1 giocatore con grade noto: '
          f'{sum(1 for r in righe if r["n_grade_in_formazione_G"] > 0)}/{len(righe)}')

    def media(v):
        v = list(v)
        return sum(v) / len(v) if v else float('nan')

    def boot_delta(righe, ka, kb, B=4000, seed=11):
        rnd = random.Random(seed)
        gruppi = collections.defaultdict(list)
        for r in righe:
            gruppi[r['fixture']].append(r)
        unita = list(gruppi.values())
        n = len(unita)
        vals = []
        for _ in range(B):
            num = 0.0; den = 0
            for _ in range(n):
                g = unita[rnd.randrange(n)]
                for r in g:
                    num += r[kb] - r[ka]; den += 1
            if den:
                vals.append(num / den)
        vals.sort()
        return vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]

    print('\n' + '=' * 72)
    print('RISULTATO -- produzione (A) vs produzione+grade riordinamento (G)')
    print('=' * 72)
    print(f'  arene: {len(righe)}   giornate: {len(set(r["fixture"] for r in righe))}')
    print(f'  tipi: {dict(collections.Counter(r["tipo"] for r in righe))}')
    print()
    print(f'  punteggio medio    utente={media(r["U_punti"] for r in righe):.2f}  '
          f'A={media(r["A_punti"] for r in righe):.2f}  G={media(r["G_punti"] for r in righe):.2f}')
    print(f'  rank medio         utente={media(r["U_rank"] for r in righe):.3f}  '
          f'A={media(r["A_rank"] for r in righe):.3f}  G={media(r["G_rank"] for r in righe):.3f}')
    print(f'  a premio (rank<=3) utente={100*media(1 if r["U_rank"]<=3 else 0 for r in righe):.1f}%  '
          f'A={100*media(1 if r["A_rank"]<=3 else 0 for r in righe):.1f}%  '
          f'G={100*media(1 if r["G_rank"]<=3 else 0 for r in righe):.1f}%')
    print(f'  netto medio essenze utente={media(r["U_premio"]-r["costo"] for r in righe):.1f}  '
          f'A={media(r["A_premio"]-r["costo"] for r in righe):.1f}  '
          f'G={media(r["G_premio"]-r["costo"] for r in righe):.1f}')

    for r in righe:
        r['_A_podio'] = 1.0 if r['A_rank'] <= 3 else 0.0
        r['_G_podio'] = 1.0 if r['G_rank'] <= 3 else 0.0
        r['_A_netto'] = float(r['A_premio'] - r['costo'])
        r['_G_netto'] = float(r['G_premio'] - r['costo'])
        r['_A_rank'] = float(r['A_rank']); r['_G_rank'] = float(r['G_rank'])
        r['_A_punti'] = float(r['A_punti']); r['_G_punti'] = float(r['G_punti'])

    print('\n  delta G-A, bootstrap appaiato su GIORNATE (mazzo fisso), IC95:')
    for nome, ka, kb in (('punteggio', '_A_punti', '_G_punti'),
                         ('rank (neg=G meglio)', '_A_rank', '_G_rank'),
                         ('podio (rank<=3, %)', '_A_podio', '_G_podio'),
                         ('netto essenze', '_A_netto', '_G_netto')):
        d = media(r[kb] - r[ka] for r in righe)
        lo, hi = boot_delta(righe, ka, kb)
        print(f'    {nome:22s} {d:+.3f}   IC95 [{lo:+.3f}, {hi:+.3f}]')

    print('\n  sovrapposizione A vs G:')
    print(f'    carte in comune su 5: media {media(r["overlap"] for r in righe):.3f}')
    dist = collections.Counter(r['overlap'] for r in righe)
    for k in sorted(dist):
        print(f'      {k}/5 : {dist[k]:4d} arene ({100*dist[k]/len(righe):.1f}%)')
    print(f'    formazioni IDENTICHE: {sum(1 for r in righe if r["identiche"])}/{len(righe)} '
          f'({100*media(1 if r["identiche"] else 0 for r in righe):.1f}%)')

    with open(os.path.join(SP, 'p12_backtest_formazione_grade_out.json'), 'w', encoding='utf-8') as fh:
        json.dump({
            'data_min_grade': data_min, 'n_fixture_totali': len(pool_per_gw),
            'n_fixture_ammesse': len(fixtures_ammesse), 'n_fixture_escluse': fixtures_escluse,
            'copertura_grade_pct': (100 * copertura_con_grade / copertura_candidati) if copertura_candidati else None,
            'righe': righe,
        }, fh, ensure_ascii=False)


if __name__ == '__main__':
    main()
