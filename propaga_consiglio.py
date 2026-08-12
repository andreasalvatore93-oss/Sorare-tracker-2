"""Propaga i 4 build_consiglio_<ruolo>.py da formazione_mls (CANONICO) a TUTTE
le leghe -- stesso principio di propaga_modello.py, ma per gli script che
aggregano i file prediction_*.txt in un consiglio_*.txt per ruolo.

PERCHE'. A differenza di build_formazione_finale.py (che il generatore
importa SEMPRE E SOLO dalla copia mls, le altre 25 sono codice morto --
verificato 12/08/2026), i build_consiglio_<ruolo>.py sono chiamati
DAVVERO uno per lega: ognuno legge le prediction_*.txt della PROPRIA lega e
scrive il PROPRIO consiglio_*.txt. Un fix a questi file (qui: il badge
"fixture ambigua", marker AMBIGUO_FIXTURE gia' scritto dai predict) va
quindi propagato per davvero, non e' un cambio-in-un-posto-solo.

COSA cambia per lega: solo i due token di percorso (OUTPUT_DIR,
DISCOVERY_FILE). Il resto -- inclusi i commenti che citano "mls_gk_all" o
"test_mls_fwd_all.py" -- resta identico apposta: sono commenti storici mai
adattati per lega nemmeno prima di questo script (verificato confrontando
arabia/argentina), quindi propagare la loro forma attuale non introduce
nessuna regressione visibile.

Uso:
    python propaga_consiglio.py            # propaga a tutte
    python propaga_consiglio.py --check    # solo verifica (nessuna scrittura)
"""
import glob
import os
import sys

CANON = 'formazione_mls'
FILES = ['build_consiglio.py', 'build_consiglio_def.py', 'build_consiglio_gk.py', 'build_consiglio_mid.py']


def _leghe():
    dirs = {os.path.dirname(os.path.dirname(p))
            for p in glob.glob('formazione_*/consiglio/build_consiglio.py')}
    return sorted(dirs)


def adatta(testo, lega):
    """Sostituisce SOLO i due token di percorso -- stesso ordine di
    propaga_modello.adatta (prima il piu' specifico), stessa cautela: NON
    tocca 'test_mls_fwd_all.py' (nome fisso del predict FWD, uguale in ogni
    lega, non un token di lega) ne' i commenti storici "mls_<ruolo>_all"."""
    t = testo
    t = t.replace('formazione_mls/', 'formazione_%s/' % lega)
    t = t.replace('/output/mls_', '/output/%s_' % lega)
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
            src = os.path.join(CANON, 'consiglio', fn)
            dst = os.path.join(legadir, 'consiglio', fn)
            if not os.path.exists(src):
                problemi.append('manca canonico %s' % src)
                continue
            if not os.path.isdir(os.path.dirname(dst)):
                continue  # la lega non ha quel ruolo/cartella
            nuovo = adatta(open(src, encoding='utf-8').read(), lega)
            # residuo sospetto: OUTPUT_DIR/DISCOVERY_FILE non adattati sono un bug
            for cattivo in ("OUTPUT_DIR = 'formazione_mls/", "'formazione_mls/output/mls_"):
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
