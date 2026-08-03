"""Propaga il modello di previsione da formazione_mls (CANONICO) a TUTTE le leghe.

PERCHE'. Ogni lega aveva la sua copia di predict/test_gk|def|mid|fwd.py, e le
copie erano DIVERSE: leghe diverse giravano modelli diversi. Un miglioramento
(es. il blend porta-inviolata del portiere) finiva solo su MLS. Da qui in poi il
modello si cambia SOLO in formazione_mls/predict/*.py e si lancia questo script:
tutte le leghe -- e quindi lo SCOUTING, che gira gli stessi
formazione_<lega>/predict/test_*.py via la matrice -- eseguono lo STESSO modello.

COSA cambia per lega: solo i token FUNZIONALI (i path di output/discovery e la
stringa della lega passata a opponent_strength). Il resto e' identico. I
commenti che citano 'formazione_mls/...' restano tali o si adattano: sono inerti.

Uso:
    python propaga_modello.py            # propaga a tutte
    python propaga_modello.py --check    # solo verifica (nessuna scrittura)
"""
import glob
import os
import sys

CANON = 'formazione_mls'
FILES = ['test_gk.py', 'test_def.py', 'test_mid.py', 'test_mls_fwd_all.py']


def _leghe():
    dirs = {os.path.dirname(os.path.dirname(p))
            for p in glob.glob('formazione_*/predict/test_gk.py')}
    return sorted(dirs)


def adatta(testo, lega):
    """Sostituisce i SOLI token di lega. Ordine importante: prima i path piu'
    specifici."""
    t = testo
    t = t.replace('formazione_mls/', 'formazione_%s/' % lega)  # path cartella lega
    t = t.replace('/output/mls_', '/output/%s_' % lega)        # output/discovery per ruolo
    t = t.replace("league='mls'", "league='%s'" % lega)        # parametro/chiamate opponent
    t = t.replace("'mls', '", "'%s', '" % lega)                # opponent_strength(lega, ruolo, ...)
    t = t.replace('block_mls_', 'block_%s_' % lega)            # marker circuit breaker per-lega
    return t


def main():
    check = '--check' in sys.argv
    scritti = 0
    problemi = []
    for legadir in _leghe():
        lega = os.path.basename(legadir).replace('formazione_', '')
        if lega == 'mls':
            continue
        for fn in FILES:
            src = os.path.join(CANON, 'predict', fn)
            dst = os.path.join(legadir, 'predict', fn)
            if not os.path.exists(src):
                problemi.append('manca canonico %s' % src)
                continue
            if not os.path.isdir(os.path.dirname(dst)):
                continue  # la lega non ha quel ruolo/cartella
            nuovo = adatta(open(src, encoding='utf-8').read(), lega)
            # residui sospetti: un token di lega non sostituito e' un bug
            for cattivo in ('formazione_mls/', "league='mls'", '/output/mls_'):
                if cattivo in nuovo:
                    problemi.append('%s: residuo %r' % (dst, cattivo))
            if not check:
                with open(dst, 'w', encoding='utf-8') as f:
                    f.write(nuovo)
            scritti += 1
    print('%s %d file (%d leghe x %d ruoli).'
          % ('Verificati' if check else 'Propagati', scritti, len(_leghe()) - 1, len(FILES)))
    if problemi:
        print('PROBLEMI (%d):' % len(problemi))
        for p in problemi[:20]:
            print('  ' + p)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
