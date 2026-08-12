# -*- coding: utf-8 -*-
"""Il file-sveglia tiene fuori dall'artifact quello che non e' di questo job?

Zero rete. Costruisce un finto repo con la stessa forma di quello vero e
recita la sequenza di un job con `clean: false`:

  - nella cartella c'e' gia' l'output del job PRECEDENTE (avanzo)
  - arriva un file da un artifact (copy2 -> mtime vecchio)
  - si scrive il marker
  - il job produce il SUO output
  - stage deve caricare solo quest'ultimo

Lanciare dalla root del repo:
    python test_marker.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

QUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.abspath(
    os.path.join(os.getcwd(), 'pipeline_artifacts.py')))
MODULO = os.path.join(os.getcwd(), 'pipeline_artifacts.py')


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def scrivi(path, testo, quando=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(testo)
    if quando is not None:
        os.utime(path, (quando, quando))


def main():
    tmp = tempfile.mkdtemp(prefix='provamarker_')
    os.chdir(tmp)
    shutil.copy2(MODULO, 'pipeline_artifacts.py')

    sh('git', 'init', '-q')
    sh('git', 'config', 'user.email', 'p@p')
    sh('git', 'config', 'user.name', 'prova')
    D = 'formazione_turchia/output/turchia_mid_all'
    scrivi(D + '/prediction_gia_su_main.txt', 'stava gia su main\n')
    sh('git', 'add', '-A')
    sh('git', 'commit', '-qm', 'base')

    vecchio = time.time() - 3600      # un'ora fa

    # 1. avanzo del job precedente sulla stessa macchina (clean:false)
    scrivi(D + '/prediction_AVANZO_run_vecchia.txt', 'di un altro job\n', vecchio)
    # 2. file arrivato da un artifact: copy2 gli tiene l'mtime del produttore
    scrivi(D + '/prediction_DA_ARTIFACT.txt', 'da un altro job di questa run\n', vecchio)
    # 3. un file gia' su main ma modificato dal job precedente
    scrivi(D + '/prediction_gia_su_main.txt', 'modificato dal job prima\n', vecchio)

    # --- ora zero ---
    r = subprocess.run([sys.executable, 'pipeline_artifacts.py', 'marker'],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    time.sleep(1.2)   # oltre la tolleranza di 1s

    # 4. il lavoro vero di QUESTO job
    scrivi(D + '/prediction_MIO.txt', 'prodotto adesso\n')
    scrivi(D + '/.game_log_cache/tizio_gamelog.json', '{}\n')

    r = subprocess.run(
        [sys.executable, 'pipeline_artifacts.py', 'stage', '_stage',
         r'^formazione_[^/]+/output/'],
        capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr)
        return 1

    caricati = set()
    for dirpath, _d, files in os.walk('_stage'):
        for n in files:
            rel = os.path.relpath(os.path.join(dirpath, n), '_stage')
            caricati.add(rel.replace(os.sep, '/'))
    caricati.discard('_stage_manifest.txt')

    atteso = {
        D + '/prediction_MIO.txt',
        D + '/.game_log_cache/tizio_gamelog.json',
    }
    print('')
    print('caricati : %s' % sorted(caricati))
    print('attesi   : %s' % sorted(atteso))
    ok = caricati == atteso
    print('')
    print('ESITO: %s' % ('OK' % () if ok else 'FALLITO'))
    if not ok:
        print('  in piu\' : %s' % sorted(caricati - atteso))
        print('  mancanti: %s' % sorted(atteso - caricati))

    # --- controprova: senza marker si torna al comportamento di prima ---
    os.remove('.pipeline_marker')
    shutil.rmtree('_stage')
    r = subprocess.run(
        [sys.executable, 'pipeline_artifacts.py', 'stage', '_stage',
         r'^formazione_[^/]+/output/'],
        capture_output=True, text=True)
    n = sum(len(f) for _p, _d, f in os.walk('_stage')) - 1
    print('senza marker: %d file (deve essere 5, cioe\' tutto)' % n)
    ok = ok and n == 5

    os.chdir(QUI)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
