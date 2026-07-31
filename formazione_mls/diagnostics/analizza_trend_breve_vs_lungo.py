"""Il calo di forma recente predice qualcosa, oltre al livello del giocatore?
(31/07, proposta dell'utente)

DOMANDA. Preso un giocatore con forma DECRESCENTE nel breve ma solida nel
lungo (es. L5=45 < L10=50 < L40=55), la partita successiva va peggio del suo
livello abituale, o il calo era rumore e rimbalza?

PERCHE' IL DISEGNO INGENUO NON FUNZIONA. Confrontare la partita successiva con
L5 troverebbe SEMPRE un rimbalzo, anche su dati completamente casuali: se L5 e'
basso, in parte lo e' per caso, e la media successiva risale per pura
regressione verso la media. Sarebbe un artefatto statistico, non un segnale.

DISEGNO USATO. Per ogni giocatore si cammina in avanti nel tempo (walk-forward,
mai guardando il futuro) e a ogni partita t si calcolano le medie sulle SOLE
partite precedenti. Poi si misura il RESIDUO: quanto la partita t si discosta
dal livello di LUNGO periodo del giocatore. Confrontando il residuo medio fra
chi e' in calo, chi e' stabile e chi e' in crescita, il livello del giocatore
si annulla e resta solo l'effetto della forma. Se i tre gruppi hanno lo stesso
residuo, la forma recente non aggiunge nulla al livello.

Si riporta anche il residuo rispetto a L10, che e' cio' che predirebbe un
modello a memoria corta: serve a vedere QUALE fra livello lungo e forma recente
sia il predittore migliore, non solo se c'e' differenza fra gruppi.

FINESTRA LUNGA = 20, non 40: i detail cache si fermano a ~40 partite per
giocatore, quindi un L40 vero non lascerebbe nulla da predire. L20 e' il piu'
lungo che consenta un campione utile (~4250 punti di test).

Uso:  python formazione_mls/diagnostics/analizza_trend_breve_vs_lungo.py
      SOGLIA_CALO=2 python formazione_mls/diagnostics/analizza_trend_breve_vs_lungo.py
"""
import glob
import json
import math
import os
import statistics
from collections import defaultdict

LUNGA = int(os.environ.get('FINESTRA_LUNGA', '20'))
MEDIA = 10
BREVE = 5
# Quanto deve essere marcato il calo per contare come tale (punti di scarto fra
# una finestra e l'altra). Con 0 basta un ordinamento qualsiasi, e si finisce
# per classificare come "in calo" anche differenze da nulla.
SOGLIA = float(os.environ.get('SOGLIA_CALO', '2'))
MIN_PARTITE = LUNGA + 5


def carica():
    """slug -> (ruolo, [(data, score), ...] ordinati nel tempo)."""
    sep = chr(92)
    out = {}
    for path in glob.glob('dati_globali/detail_cache/*/*/*_detail_cache.json'):
        ruolo = path.replace(sep, '/').split('/')[-2]
        slug = os.path.basename(path).replace('_detail_cache.json', '')
        if slug in out:
            continue
        try:
            d = json.load(open(path, encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        partite = []
        for v in d.values():
            if not isinstance(v, dict) or v.get('score') is None:
                continue
            g = v.get('anyGame') or {}
            data = (g.get('date') or '')[:10]
            if data:
                partite.append((data, float(v['score'])))
        if len(partite) >= MIN_PARTITE:
            partite.sort()
            out[slug] = (ruolo, partite)
    return out


def classifica(l5, l10, l20):
    """'calo' / 'crescita' / 'stabile', con margine SOGLIA per non chiamare
    'calo' una differenza da nulla."""
    if l5 < l10 - SOGLIA and l10 < l20 - SOGLIA:
        return 'calo'
    if l5 > l10 + SOGLIA and l10 > l20 + SOGLIA:
        return 'crescita'
    return 'stabile'


def media(v):
    return sum(v) / len(v) if v else None


def main():
    dati = carica()
    print(f"Giocatori con almeno {MIN_PARTITE} partite: {len(dati)}")
    print(f"Finestre: L{BREVE} / L{MEDIA} / L{LUNGA} | soglia calo/crescita: {SOGLIA:g} pt\n")

    # ruolo -> gruppo -> lista di (residuo_vs_lungo, residuo_vs_L10)
    dati_per_ruolo = defaultdict(lambda: defaultdict(list))
    for slug, (ruolo, partite) in dati.items():
        punteggi = [s for _d, s in partite]
        for t in range(LUNGA, len(punteggi)):
            l5 = media(punteggi[t - BREVE:t])
            l10 = media(punteggi[t - MEDIA:t])
            l20 = media(punteggi[t - LUNGA:t])
            gruppo = classifica(l5, l10, l20)
            reale = punteggi[t]
            dati_per_ruolo[ruolo][gruppo].append((reale - l20, reale - l10))

    for ruolo in ('gk', 'def', 'mid', 'fwd'):
        gruppi = dati_per_ruolo.get(ruolo)
        if not gruppi:
            continue
        print("=" * 78)
        print(f"{ruolo.upper()}")
        print("=" * 78)
        print(f"  {'gruppo':<10}{'n':>7}{'residuo vs L20':>17}{'IC95%':>18}"
              f"{'residuo vs L10':>17}")
        base = None
        for gruppo in ('calo', 'stabile', 'crescita'):
            valori = gruppi.get(gruppo) or []
            if len(valori) < 30:
                print(f"  {gruppo:<10}{len(valori):>7}   campione troppo piccolo")
                continue
            r20 = [a for a, _b in valori]
            r10 = [b for _a, b in valori]
            m20, m10 = statistics.mean(r20), statistics.mean(r10)
            se = statistics.stdev(r20) / math.sqrt(len(r20))
            ic = f"[{m20 - 1.96 * se:+.2f}, {m20 + 1.96 * se:+.2f}]"
            print(f"  {gruppo:<10}{len(valori):>7}{m20:>+17.2f}{ic:>18}{m10:>+17.2f}")
            if gruppo == 'stabile':
                base = (m20, se, len(r20))

        # Il confronto che conta: "calo" contro "stabile". Se gli intervalli si
        # sovrappongono, la forma recente non porta informazione oltre al livello.
        if base and len(gruppi.get('calo') or []) >= 30:
            r20_calo = [a for a, _b in gruppi['calo']]
            m_calo = statistics.mean(r20_calo)
            se_calo = statistics.stdev(r20_calo) / math.sqrt(len(r20_calo))
            diff = m_calo - base[0]
            se_diff = math.sqrt(se_calo ** 2 + base[1] ** 2)
            z = diff / se_diff if se_diff else 0.0
            verdetto = ("SIGNIFICATIVO" if abs(z) >= 1.96 else
                        "non significativo (compatibile con zero)")
            print(f"\n  calo - stabile = {diff:+.2f} pt  (z={z:+.2f}) -> {verdetto}")
            if abs(z) < 1.96:
                print("  => la forma in calo NON predice nulla oltre al livello di lungo periodo.")
            elif diff < 0:
                print("  => chi e' in calo rende MENO del suo livello: il calo e' segnale vero.")
            else:
                print("  => chi e' in calo rende PIU' del suo livello: rimbalzo (mean reversion).")
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
