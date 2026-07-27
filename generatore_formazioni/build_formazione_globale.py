"""
build_formazione_globale.py -- Generatore Formazioni (fusione MLS + K League)

Terza versione, AGGIUNTIVA rispetto a formazione_mls/build_formazione_finale.py
e formazione_kleague/build_formazione_finale.py (che restano invariati e
continuano a funzionare da soli). Legge i consigli di ruolo GIA' PRODOTTI dai
due tool esistenti (stessi file, nessuna nuova query storica -- la cache
incrementale di entrambi viene riusata cosi' com'e'), applica un filtro
qualita' aggiuntivo (vedi quality_filter.py) e costruisce fino a 8 TIPI di
lineup Sorare in un colpo solo:

  1. MLS_IN_SEASON       -- solo carte MLS, min 4 In Season + max 1 Classic
  2. KLEAGUE_IN_SEASON    -- identico, solo carte K League
  3. MLS_ARENA            -- solo carte MLS, cap L10 FISSO 260 (vincolante)
  4. KLEAGUE_ARENA        -- identico, solo carte K League
  5. ARENA_ALLSTARS_260   -- pool MISTO MLS+K League, cap L10 fisso 260
  6. ARENA_ALLSTARS_220   -- pool misto, cap L10 fisso 220
  7. ARENA_ALLSTARS_UNCAPPED -- pool misto, nessun cap
  8. ALLSTARS             -- 7 carte, pool misto, cap 370 SOFT (bonus, non vincolo)

Riusa (import diretto, nessuna duplicazione di logica) le funzioni generiche
di formazione_mls/build_formazione_finale.py -- CardPool, build_one_lineup,
render_lineup_html, render_report_html, pick_captain, parse_consiglio,
load_card_counts, latest_consiglio -- che sono gia' indipendenti dalla lega
(lavorano su liste generiche di slug/punteggio/squadra). Le uniche cose nuove
sono qui: quali file leggere (MLS + K League), il filtro qualita', le 8
strutture di formazione, l'ordine di priorita' e il parsing dei nuovi input.

ORDINE DI PRIORITA' (deciso esplicitamente dall'utente, 27/07): In Season
(MLS poi K League) -> Arena dedicata (MLS poi K League) -> Arena All Stars
(260 -> 220 -> uncapped) -> All Stars. Un CardPool CONDIVISO tra tutti gli 8
tipi (come nei due tool singoli) fa si' che, se il pool si esaurisce, siano
le formazioni meno prioritarie a non completarsi per prime.

Output: SOLO HTML (richiesta esplicita utente), in generatore_formazioni/output/.
"""
import os
import re
import sys
import glob
import datetime
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_filter  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)


def _import_module(name, rel_path):
    path = os.path.join(_REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Import "a libreria" del tool MLS esistente -- SENZA eseguirne main() (e'
# protetto da if __name__ == '__main__'). Le funzioni generiche che riusiamo
# non contengono nulla di specifico MLS, solo logica di costruzione lineup.
bff = _import_module('mls_build_formazione_finale', 'formazione_mls/build_formazione_finale.py')

ROLES = ('GK', 'DEF', 'MID', 'FWD')

CONSIGLIO_DIRS = {
    'mls': {
        'GK': 'formazione_mls/output/mls_gk_all', 'DEF': 'formazione_mls/output/mls_def_all',
        'MID': 'formazione_mls/output/mls_mid_all', 'FWD': 'formazione_mls/output/mls_fwd_all',
    },
    'kleague': {
        'GK': 'formazione_kleague/output/kleague_gk_all', 'DEF': 'formazione_kleague/output/kleague_def_all',
        'MID': 'formazione_kleague/output/kleague_mid_all', 'FWD': 'formazione_kleague/output/kleague_fwd_all',
    },
}
DISCOVERY_DIRS = {
    'mls': {
        'GK': 'formazione_mls/output/mls_gk_discovery', 'DEF': 'formazione_mls/output/mls_def_discovery',
        'MID': 'formazione_mls/output/mls_mid_discovery', 'FWD': 'formazione_mls/output/mls_fwd_discovery',
    },
    'kleague': {
        'GK': 'formazione_kleague/output/kleague_gk_discovery', 'DEF': 'formazione_kleague/output/kleague_def_discovery',
        'MID': 'formazione_kleague/output/kleague_mid_discovery', 'FWD': 'formazione_kleague/output/kleague_fwd_discovery',
    },
}

OUTPUT_DIR = os.path.join(_HERE, 'output')

# --- Strutture degli 8 tipi (role_slots/extra_roles/max_classic come nei tool
# singoli) + parametri di comportamento per tipo, tutti espliciti qui (NON si
# riusano i dizionari per-tipo del modulo importato, le chiavi sono diverse). -
FORMATION_SHAPES = {
    'MLS_IN_SEASON': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': 1},
    'KLEAGUE_IN_SEASON': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': 1},
    'MLS_ARENA': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'KLEAGUE_ARENA': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'ARENA_ALLSTARS_260': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'ARENA_ALLSTARS_220': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'ARENA_ALLSTARS_UNCAPPED': {'role_slots': ['GK', 'DEF', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
    'ALLSTARS': {'role_slots': ['GK', 'DEF', 'DEF', 'MID', 'MID', 'FWD'], 'extra_roles': ['DEF', 'MID', 'FWD'], 'max_classic': None},
}

LABELS = {
    'MLS_IN_SEASON': 'In Season MLS', 'KLEAGUE_IN_SEASON': 'In Season K League',
    'MLS_ARENA': 'Arena MLS (cap 260)', 'KLEAGUE_ARENA': 'Arena K League (cap 260)',
    'ARENA_ALLSTARS_260': 'Arena All Stars (cap 260)', 'ARENA_ALLSTARS_220': 'Arena All Stars (cap 220)',
    'ARENA_ALLSTARS_UNCAPPED': 'Arena All Stars (uncapped)', 'ALLSTARS': 'All Stars',
}

L10_CAP_BY_TYPE = {
    'MLS_ARENA': 260.0, 'KLEAGUE_ARENA': 260.0,
    'ARENA_ALLSTARS_260': 260.0, 'ARENA_ALLSTARS_220': 220.0,  # ARENA_ALLSTARS_UNCAPPED: nessuna chiave = None
}

# Sinergia da correlazione misurata (GK-DEF/GK-MID/DEF-MID/DEF-DEF): dovunque
# TRANNE In Season, dove il target e' fisso e non c'e' beneficio (stessa
# regola gia' in produzione nei due tool singoli, confermata dall'utente
# valida anche per le Arene dedicate fuse).
VARIANCE_MODE_TYPES = {'MLS_ARENA', 'KLEAGUE_ARENA', 'ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220',
                        'ARENA_ALLSTARS_UNCAPPED', 'ALLSTARS'}

# Bonus anti-stack Sorare "Multi-club" (<3 stessa squadra): SOLO In Season e
# All Stars, mai nelle Arene (hanno il loro cap L10 obbligatorio separato).
STACK_GUARD_TYPES = {'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON', 'ALLSTARS'}

# Pannello bonus "Cap 260/370" (soft, solo segnalazione): SOLO In Season
# (soglia 260) e All Stars (soglia 370) -- le Arene hanno gia' il loro cap
# obbligatorio, non hanno questo bonus extra.
CHECK_CAP260_TYPES = {'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON', 'ALLSTARS'}

CAPTAIN_BONUS_BY_TYPE = {
    'MLS_IN_SEASON': 0.5, 'KLEAGUE_IN_SEASON': 0.5,
    'MLS_ARENA': 0.2, 'KLEAGUE_ARENA': 0.2,
    'ARENA_ALLSTARS_260': 0.2, 'ARENA_ALLSTARS_220': 0.2, 'ARENA_ALLSTARS_UNCAPPED': 0.2,
    'ALLSTARS': 0.5,
}
CAP260_THRESHOLD_BY_TYPE = {'MLS_IN_SEASON': 260.0, 'KLEAGUE_IN_SEASON': 260.0, 'ALLSTARS': 370.0}

# Estende (SOLO in memoria di questo processo, nessuna modifica al file) le
# tabelle per-tipo del modulo importato: render_lineup_html/format_lineup
# fanno CAPTAIN_BONUS_BY_TYPE.get(tipo, 0.5) sui NOSTRI nomi di tipo, quindi
# vanno registrati li' prima di chiamarle.
bff.CAPTAIN_BONUS_BY_TYPE.update(CAPTAIN_BONUS_BY_TYPE)
bff.CAP260_L10_THRESHOLD_BY_TYPE.update(CAP260_THRESHOLD_BY_TYPE)

# Ordine di generazione FISSO (priorita' decisa dall'utente).
PRIORITY_ORDER = [
    'MLS_IN_SEASON', 'KLEAGUE_IN_SEASON',
    'MLS_ARENA', 'KLEAGUE_ARENA',
    'ARENA_ALLSTARS_260', 'ARENA_ALLSTARS_220', 'ARENA_ALLSTARS_UNCAPPED',
    'ALLSTARS',
]

POOL_LEAGUE_BY_TYPE = {
    'MLS_IN_SEASON': 'mls', 'MLS_ARENA': 'mls',
    'KLEAGUE_IN_SEASON': 'kleague', 'KLEAGUE_ARENA': 'kleague',
    'ARENA_ALLSTARS_260': 'mixed', 'ARENA_ALLSTARS_220': 'mixed', 'ARENA_ALLSTARS_UNCAPPED': 'mixed',
    'ALLSTARS': 'mixed',
}


def _read_int_env(name, default=0):
    val = os.environ.get(name)
    if val is None or val.strip() == '':
        return default
    try:
        return int(val)
    except ValueError:
        return default


def parse_league_qty(raw, field_name):
    """Formato 'lega:quantita,lega:quantita' (es. 'mls:4,kleague:1'). Lega
    omessa = 0. Fail-fast su lega sconosciuta o quantita' non numerica --
    meglio fermarsi subito che generare formazioni diverse da quanto chiesto."""
    result = {'mls': 0, 'kleague': 0}
    raw = (raw or '').strip()
    if not raw:
        return result
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        if ':' not in part:
            raise SystemExit(f"ERRORE in '{field_name}': '{part}' non e' nel formato lega:quantita.")
        lega, qty = part.split(':', 1)
        lega = lega.strip().lower()
        if lega not in result:
            raise SystemExit(f"ERRORE in '{field_name}': lega '{lega}' sconosciuta (valide: mls, kleague).")
        try:
            result[lega] = int(qty.strip())
        except ValueError:
            raise SystemExit(f"ERRORE in '{field_name}': quantita' '{qty}' non numerica per lega '{lega}'.")
    return result


def load_league_role_data():
    """Ritorna (role_data, role_counts) per lega, riusando parse_consiglio/
    load_card_counts/latest_consiglio del modulo importato -- identica
    logica dei due tool singoli, solo su entrambe le leghe."""
    role_data = {'mls': {}, 'kleague': {}}
    role_counts = {'mls': {}, 'kleague': {}}
    for league in ('mls', 'kleague'):
        for role in ROLES:
            out_dir = CONSIGLIO_DIRS[league][role]
            path = bff.latest_consiglio(out_dir)
            rows = bff.parse_consiglio(path) if path else []
            counts, _ = bff.load_card_counts(DISCOVERY_DIRS[league][role])
            print(f"[{league}/{role}] {path or 'NESSUN FILE TROVATO'} -> {len(rows)} giocatori")
            role_data[league][role] = rows
            role_counts[league][role] = counts
    return role_data, role_counts


GROW_BATCH = int(os.environ.get('QUALITY_GROW_BATCH', '3'))
SLOT_RE = re.compile(r'slot (\S+) \(')


def build_quality_pools(role_data):
    """Un LazyQualityPool per (lega, ruolo), sulla lista COMPLETA (non
    filtrata) letta dai consigli -- nessuna query finche' non serve davvero
    (vedi build_one_lineup_with_growth)."""
    return {
        league: {role: quality_filter.LazyQualityPool(role, league, role_data[league][role])
                  for role in ROLES}
        for league in ('mls', 'kleague')
    }


def _view_for(pools, pool_league, role):
    if pool_league == 'mixed':
        combined = pools['mls'][role].passing + pools['kleague'][role].passing
        combined.sort(key=lambda r: r['atteso'], reverse=True)
        return combined
    return pools[pool_league][role].passing


def _grow_for(pools, pool_league, role, batch):
    if pool_league == 'mixed':
        return pools['mls'][role].grow(batch) + pools['kleague'][role].grow(batch)
    return pools[pool_league][role].grow(batch)


def _raw_view_for(role_data, pool_league, role):
    if pool_league == 'mixed':
        combined = role_data['mls'][role] + role_data['kleague'][role]
        combined.sort(key=lambda r: r['atteso'], reverse=True)
        return combined
    return role_data[pool_league][role]


def build_one_lineup_with_growth(shape, pool_league, role_data, pools, card_pool, l10_cap,
                                  apply_stack_guard, variance_mode, apply_positive_synergy=True,
                                  strict_gk_anti_synergy=False):
    """Se il tipo ha un cap L10 obbligatorio (Arena dedicate/All Stars), il
    filtro qualita' NON si applica (27/07, richiesta esplicita utente): sono
    in tensione diretta -- L5/L10/L40>=35 esclude proprio le carte economiche
    che servirebbero per stare sotto il cap, e il vincolo hard sul cap ora
    vive in bff.build_one_lineup stesso (riserva di budget per gli slot
    futuri, fallisce piuttosto che sforare). Si usa quindi il pool GREZZO
    (tutte le carte scoperte per la lega/le leghe coinvolte), zero query di
    qualita' per questi tipi.

    Per i tipi SENZA cap (In Season, All Stars, Arena All Stars uncapped) il
    filtro qualita' resta attivo: si interrogano solo i candidati che
    servono, e se manca un candidato per uno slot si interrogano i prossimi
    (GROW_BATCH alla volta) e si riprova, finche' la formazione si completa
    o il pool scoperto e' davvero esaurito."""
    if l10_cap is not None:
        role_data_view = {role: _raw_view_for(role_data, pool_league, role) for role in ROLES}
        return bff.build_one_lineup(shape, role_data_view, card_pool, l10_cap=l10_cap,
                                     apply_stack_guard=apply_stack_guard, variance_mode=variance_mode,
                                     apply_positive_synergy=apply_positive_synergy,
                                     strict_gk_anti_synergy=strict_gk_anti_synergy)

    while True:
        role_data_view = {role: _view_for(pools, pool_league, role) for role in ROLES}
        formazione, error, l10_ok, stack_perso = bff.build_one_lineup(
            shape, role_data_view, card_pool, l10_cap=l10_cap,
            apply_stack_guard=apply_stack_guard, variance_mode=variance_mode,
            apply_positive_synergy=apply_positive_synergy, strict_gk_anti_synergy=strict_gk_anti_synergy)
        if not error:
            return formazione, None, l10_ok, stack_perso

        m = SLOT_RE.search(error)
        raw_slot = m.group(1) if m else ''
        if raw_slot == 'extra':
            roles_to_grow = shape['extra_roles']
        else:
            role = re.sub(r'\d+$', '', raw_slot)
            roles_to_grow = [role] if role in ROLES else ROLES

        progressed = any(_grow_for(pools, pool_league, r, GROW_BATCH) > 0 for r in roles_to_grow)
        if not progressed:
            return None, error, l10_ok, stack_perso


def generate_lineups_for_type(tipo, count, role_data, pools, card_pool, lineup_html_blocks):
    if count <= 0:
        return 0, 0
    shape = FORMATION_SHAPES[tipo]
    pool_league = POOL_LEAGUE_BY_TYPE[tipo]
    cap = L10_CAP_BY_TYPE.get(tipo)
    stack_guard = tipo in STACK_GUARD_TYPES
    variance_mode = tipo in VARIANCE_MODE_TYPES
    check_cap260 = tipo in CHECK_CAP260_TYPES
    label = LABELS[tipo]
    # 27/07, richiesta esplicita utente, stesso fix identico nei due tool
    # singoli: con 2+ In Season richieste (MLS o K League, ciascuna lega
    # conta a se'), solo la prima usa la sinergia GK-DEF soft, le altre sono
    # greedy puro; in ENTRAMBI i casi il vincolo portiere-vs-avversario
    # diventa DURO. Con 1 sola In Season di quella lega, comportamento
    # INVARIATO. Le Arene (dedicate o All Stars) non sono toccate.
    in_season_multi = tipo in ('MLS_IN_SEASON', 'KLEAGUE_IN_SEASON') and count >= 2
    # Varianza capitano (27/07, richiesta esplicita utente, stesso fix
    # identico nei due tool singoli): scope per tipo (uno degli 8 qui).
    captained_slugs = set()

    generated, totale = 0, 0
    for idx in range(1, count + 1):
        strict_gk_anti_synergy = in_season_multi
        apply_positive_synergy = not in_season_multi or idx == 1
        formazione, error, l10_ok, stack_perso = build_one_lineup_with_growth(
            shape, pool_league, role_data, pools, card_pool, cap, stack_guard, variance_mode,
            apply_positive_synergy, strict_gk_anti_synergy)
        if error:
            msg = f"Formazione {label} #{idx}: NON GENERATA — {error}"
            print(msg)
            lineup_html_blocks.append(f'<p class="error-block">{msg}</p>')
            break
        lineup_html_blocks.append(bff.render_lineup_html(
            label, idx, formazione, card_pool, l10_cap=cap, l10_cap_rispettato=l10_ok,
            stack_bonus_perso=stack_perso, check_cap260=check_cap260, tipo=tipo,
            apply_stack_guard=stack_guard, avoid_captain_slugs=captained_slugs))
        _cap_slot, cap_row, _cap_type = bff.pick_captain(formazione, captained_slugs)
        captained_slugs.add(cap_row['slug'])
        totale += sum(row['atteso'] for _, row, _ in formazione)
        generated += 1
        print(f"Formazione {label} #{idx}: generata ({sum(r['atteso'] for _, r, _ in formazione)} pt)")
    return generated, totale


def main():
    in_season_req = parse_league_qty(os.environ.get('IN_SEASON', 'mls:1,kleague:1'), 'in_season')
    arena_dedicata_req = parse_league_qty(os.environ.get('ARENA_DEDICATA', 'mls:0,kleague:0'), 'arena_dedicata')
    arena_allstars_260 = _read_int_env('ARENA_ALLSTARS_260', 0)
    arena_allstars_220 = _read_int_env('ARENA_ALLSTARS_220', 0)
    arena_allstars_uncapped = _read_int_env('ARENA_ALLSTARS_UNCAPPED', 0)
    allstars_qty = _read_int_env('ALLSTARS', 0)

    counts = {
        'MLS_IN_SEASON': in_season_req['mls'], 'KLEAGUE_IN_SEASON': in_season_req['kleague'],
        'MLS_ARENA': arena_dedicata_req['mls'], 'KLEAGUE_ARENA': arena_dedicata_req['kleague'],
        'ARENA_ALLSTARS_260': arena_allstars_260, 'ARENA_ALLSTARS_220': arena_allstars_220,
        'ARENA_ALLSTARS_UNCAPPED': arena_allstars_uncapped, 'ALLSTARS': allstars_qty,
    }
    num_totale = sum(counts.values())
    print(f"Formazioni richieste: totale={num_totale} -> " +
          ", ".join(f"{LABELS[t]}={counts[t]}" for t in PRIORITY_ORDER))

    role_data, role_counts = load_league_role_data()

    for league in ('mls', 'kleague'):
        if not all(role_data[league].get(r) for r in ROLES):
            print(f"\nATTENZIONE: la lega '{league}' ha almeno un ruolo senza consiglio disponibile "
                  f"-- le formazioni di quella lega/pool misto potrebbero non completarsi.")

    pools = build_quality_pools(role_data)

    merged_counts = {
        role: {**role_counts['mls'][role], **role_counts['kleague'][role]}
        for role in ROLES
    }
    card_pool = bff.CardPool(merged_counts)

    run_number = os.environ.get('GITHUB_RUN_NUMBER')
    lineup_html_blocks = []
    generated_by_type = {}
    grand_total = 0
    for tipo in PRIORITY_ORDER:
        generated, totale = generate_lineups_for_type(tipo, counts[tipo], role_data, pools, card_pool, lineup_html_blocks)
        generated_by_type[tipo] = generated
        grand_total += totale

    total_generated = sum(generated_by_type.values())
    print(f"\nFormazioni generate: {total_generated}/{num_totale}")
    if total_generated > 1:
        print(f"TOTALE COMPLESSIVO: {grand_total} pt")

    tot_checked = sum(p.checked_idx for league in pools.values() for p in league.values())
    tot_passed = sum(len(p.passing) for league in pools.values() for p in league.values())
    print(f"Filtro qualita' (lazy): {tot_checked} carte interrogate, {tot_passed} promosse "
          f"(su un pool scoperto totale di {sum(len(p.full) for league in pools.values() for p in league.values())}).")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
    run_suffix = f"_run{run_number}" if run_number else ""
    page_title = f"Generatore Formazioni{' — run #' + run_number if run_number else ''}"
    page_subhead = (f"Generato {datetime.datetime.utcnow().strftime('%d/%m/%Y %H:%M')}Z — "
                     f"totale={num_totale} (" +
                     ", ".join(f"{LABELS[t]}={counts[t]}" for t in PRIORITY_ORDER) + ")")
    footer_html = ("Fusione MLS + K League. Max 1 carta CLASSIC solo per In Season. Filtro qualita' "
                    f"L5/L10/L40 tutti >= {quality_filter.MIN_QUALITY_SCORE} applicato prima della scelta.")
    html_text = bff.render_report_html(page_title, page_subhead, lineup_html_blocks, footer_html)
    html_path = os.path.join(OUTPUT_DIR, f'generatore_formazioni{run_suffix}_{ts}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    print(f"\nReport visivo salvato in: {html_path}")


if __name__ == '__main__':
    main()
