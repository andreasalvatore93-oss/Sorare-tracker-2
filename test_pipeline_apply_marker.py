# -*- coding: utf-8 -*-
"""I file RICEVUTI da un artifact restano fuori dall'artifact che si carica?

Riproduce la sequenza vera di un job (scarico -> apply -> marker -> lavoro ->
stage) SENZA le pause artificiali del test precedente: apply e marker girano
attaccati, che e' esattamente la condizione in cui il difetto si vedeva.

Atteso: nell'artifact finisce solo il file prodotto dal job, non quelli
ricevuti.

    python test_apply_marker.py
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

MODULO = os.path.join(os.getcwd(), 'pipeline_artifacts.py')
QUI = os.getcwd()


def scrivi(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w', encoding='utf-8').write(t)


def main():
    tmp = tempfile.mkdtemp(prefix='provaapply_')
    os.chdir(tmp)
    shutil.copy2(MODULO, 'pipeline_artifacts.py')
    subprocess.run(['git', 'init', '-q'], check=True)
    subprocess.run(['git', 'config', 'user.email', 'p@p'], check=True)
    subprocess.run(['git', 'config', 'user.name', 'prova'], check=True)
    D = 'formazione_turchia/output/turchia_mid_all'
    scrivi(D + '/gia_su_main.txt', 'base\n')
    subprocess.run(['git', 'add', '-A'], check=True)
    subprocess.run(['git', 'commit', '-qm', 'base'], check=True)

    # un artifact in arrivo, come lo lascia actions/download-artifact:
    # scritto ADESSO, quindi con la data di adesso
    scrivi('_artifacts/pred-0/' + D + '/prediction_RICEVUTA.txt', 'di un altro job\n')
    scrivi('_artifacts/pred-0/_stage_manifest.txt', 'x\n')

    def sh(*a):
        r = subprocess.run([sys.executable, 'pipeline_artifacts.py'] + list(a),
                           capture_output=True, text=True)
        print('   ' + (r.stdout.strip().replace('\n', '\n   ') or r.stderr.strip()[:200]))
        return r

    print('apply ->')
    sh('apply', '_artifacts')
    print('marker (subito dopo, senza pause) ->')
    sh('marker')
    # il lavoro vero di questo job
    scrivi(D + '/prediction_MIA.txt', 'prodotta adesso\n')
    print('stage ->')
    sh('stage', '_stage', r'^formazione_[^/]+/output/')

    caricati = set()
    for dp, _d, ff in os.walk('_stage'):
        for n in ff:
            rel = os.path.relpath(os.path.join(dp, n), '_stage').replace(os.sep, '/')
            caricati.add(rel)
    caricati.discard('_stage_manifest.txt')

    atteso = {D + '/prediction_MIA.txt'}
    print('')
    print('caricati: %s' % sorted(caricati))
    print('attesi  : %s' % sorted(atteso))
    ok = caricati == atteso
    print('')
    print('ESITO: %s' % ('OK -- il ricevuto resta fuori' if ok else 'FALLITO'))
    if not ok:
        print('  in piu\': %s' % sorted(caricati - atteso))
        print('  mancanti: %s' % sorted(atteso - caricati))

    # controprova: il file ricevuto DEVE comunque esserci sul disco
    presente = os.path.exists(D + '/prediction_RICEVUTA.txt')
    print('il file ricevuto e\' comunque sul disco: %s' % presente)
    ok = ok and presente

    os.chdir(QUI)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
