"""Batching via alias GraphQL per formazione()/premi (10/08/2026).

Idea: una richiesta HTTP puo' portare N campi alias invece di uno solo,
ripetendo la stessa selezione con nomi diversi (c0, c1, ...) e variabili
diverse ($s0, $s1, ...). Stessa query, stesso schema, nessuna
introspezione -- solo il client che chiede piu' cose in un colpo.

Riusa `ricostruisci_manager.graphql()` (stesso retry/429/fallback-cookie
gia' verificato), non riscrive la sessione HTTP. Riusa gli STESSI campi di
`FORMAZIONE_QUERY`/la query premi di `estrai_archivio_manager.py` --
copiati identici, non re-inventati, cosi' il risultato per singolo
elemento e' garantito uguale a quello delle funzioni una-alla-volta.

LIMITE REALE DI COMPLESSITA' (misurato 10/08/2026, non e' il fattore
10-15x stimato a occhio prima di provare): Sorare capa la query a
complessita' 500 senza APIKEY (con l'APIKEY salirebbe a 30000, richiesta
e mai arrivata). `formazione()` e' pesante (powerBreakdown annidato):
batch=3 sta a 393 di complessita', batch=4 sfora gia' (525). I premi sono
leggeri: batch=10 sta sotto soglia, batch=15 sfora. Quindi il guadagno
vero e' ~3x sulle formazioni e ~8-10x sui premi, non un fattore unico.
Verificato che batch=3 (formazione) e batch=10 (premi) danno risultati
IDENTICI, elemento per elemento, alle funzioni RM.formazione()/
premi_per_posizione() una-alla-volta sullo stesso input reale (8 formazioni
+ 8 leaderboard di football-21-24-jul-2026).
"""
import ricostruisci_manager as RM

CAMPI_FORMAZIONE = """
      so5Lineup {
        user { slug }
        so5Rankings { ranking score so5Leaderboard { slug } }
        so5Appearances {
          score
          position
          captain
          player { slug displayName activeClub { slug name } }
          anyCard {
            slug
            rarityTyped
            inSeasonEligible
            ... on Card {
              xp
              u23Eligible
              powerBreakdown {
                seasonBasisPoints
                collectionBasisPoints
                xpBasisPoints
                scarcityBasisPoints
                specialEditionCardsBasisPoints
                activeClubsBasisPoints
                nationalityBasisPoints
                positionsBasisPoints
              }
            }
          }
        }
      }
"""

CAMPI_PREMI = """
      rewardsConfig {
        ranking { ranks rewardConfigs { __typename ... on CardShardRewardConfig { quantity } } }
      }
"""


def _a_lotti(lista, dimensione):
    for i in range(0, len(lista), dimensione):
        yield lista[i:i + dimensione]


def _parse_formazione(cont):
    """Stessa logica di RM.formazione(), a partire dal nodo gia' scaricato."""
    if not cont:
        return None, None, None
    lineup = cont.get('so5Lineup') or {}
    contender_slug = cont.get('slug') or ''
    piazzamento = None
    for r in lineup.get('so5Rankings') or []:
        if ((r.get('so5Leaderboard') or {}).get('slug') or '') in contender_slug:
            piazzamento = {'rank': r.get('ranking'), 'punteggio': r.get('score')}
            break
    carte = []
    for a in lineup.get('so5Appearances') or []:
        carta = a.get('anyCard') or {}
        pb = carta.get('powerBreakdown') or {}
        bonus = sum(v or 0 for k, v in pb.items() if k.endswith('BasisPoints')) / 10000.0
        carte.append({
            'slug': ((a.get('player') or {}).get('slug')),
            'nome': ((a.get('player') or {}).get('displayName')),
            'squadra': ((((a.get('player') or {}).get('activeClub')) or {}).get('slug')),
            'ruolo': a.get('position'),
            'capitano': bool(a.get('captain')),
            'punteggio': a.get('score'),
            'rarita': carta.get('rarityTyped'),
            'carta': carta.get('slug'),
            'xp': carta.get('xp'),
            'bonus_carta': round(bonus, 4),
            'in_season': carta.get('inSeasonEligible'),
            'u23': carta.get('u23Eligible'),
        })
    return carte, ((lineup.get('user') or {}).get('slug')), piazzamento


def formazioni_batch(contender_slugs, batch_size=3):
    """slug -> (carte, manager, piazzamento), stesso output di RM.formazione()
    ma N per richiesta HTTP invece di 1."""
    out = {}
    for lotto in _a_lotti(list(contender_slugs), batch_size):
        parti_query = []
        variabili = {}
        for i, slug in enumerate(lotto):
            parti_query.append(f'c{i}: so5LeaderboardContender(slug: $s{i}) {{ slug {CAMPI_FORMAZIONE} }}')
            variabili[f's{i}'] = slug
        dichiarazioni = ', '.join(f'$s{i}: String!' for i in range(len(lotto)))
        query = f'query FormazioniBatch({dichiarazioni}) {{ so5 {{ {" ".join(parti_query)} }} }}'
        d = RM.graphql(query, variabili)
        if d.get('errors'):
            for slug in lotto:
                out[slug] = (None, None, None)
            continue
        so5 = (d.get('data') or {}).get('so5') or {}
        for i, slug in enumerate(lotto):
            out[slug] = _parse_formazione(so5.get(f'c{i}'))
    return out


def premi_batch(leaderboard_slugs, batch_size=10):
    """leaderboard_slug -> [(pos_1based, quantity)], N per richiesta invece di 1."""
    out = {}
    for lotto in _a_lotti(list(leaderboard_slugs), batch_size):
        parti_query = []
        variabili = {}
        for i, slug in enumerate(lotto):
            parti_query.append(f'p{i}: so5Leaderboard(slug: $s{i}) {{ {CAMPI_PREMI} }}')
            variabili[f's{i}'] = slug
        dichiarazioni = ', '.join(f'$s{i}: String!' for i in range(len(lotto)))
        query = f'query PremiBatch({dichiarazioni}) {{ so5 {{ {" ".join(parti_query)} }} }}'
        d = RM.graphql(query, variabili, con_cookie=False)
        if d.get('errors'):
            for slug in lotto:
                out[slug] = None
            continue
        so5 = (d.get('data') or {}).get('so5') or {}
        for i, slug in enumerate(lotto):
            lb = so5.get(f'p{i}')
            if not lb or not lb.get('rewardsConfig'):
                out[slug] = None
                continue
            premi, pos = [], 1
            for fascia in (lb['rewardsConfig'].get('ranking') or []):
                larghezza = fascia.get('ranks') or 1
                q = None
                for x in (fascia.get('rewardConfigs') or []):
                    if x.get('__typename') == 'CardShardRewardConfig':
                        q = x.get('quantity')
                        break
                for _ in range(larghezza):
                    premi.append((pos, q))
                    pos += 1
            out[slug] = premi
    return out
