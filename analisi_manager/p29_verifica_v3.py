"""PASSO 3 (BRIEF_SONNET_APPLICA_SOGLIE_2026-08-09 §4, controllo obbligatorio):
consiglio_arena.py puntato a arene_storico_full_v3.json deve riprodurre DA
SOLO (senza monkeypatch, usando la sua premi_osservati() gia' modificata) i
valori che stiamo mettendo in produzione: 264.5/247.1/279.6/256.5 (pareggio)
e 6.96/5.11/5.88/2.46 (guadagno/pt). Stessa sigma per tipo del Passo 2
(RIUSATA, non rifatta): cap260 50.52, cap220 46.70, Uncapped 53.72,
Beginner 50.18.
SOLO MISURA.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ['ARCHIVIO_ARENE'] = 'dati_globali/arene_storico_full_v3.json'
import consiglio_arena as C

SIGMA_PER_TIPO = {'cap 260': 50.52, 'cap 220': 46.70, 'Uncapped': 53.72, 'Beginner': 50.18}
ATTESI = {'cap 260': (264.5, 6.96), 'cap 220': (247.1, 5.11), 'Uncapped': (279.6, 5.88), 'Beginner': (256.5, 2.46)}


def guadagno_per_punto(pareggio_val, avversari, premi, sigma, tipo):
    i_meno = C.incasso_medio(pareggio_val - 5, avversari, premi, sigma=sigma, tipo=tipo)
    i_piu = C.incasso_medio(pareggio_val + 5, avversari, premi, sigma=sigma, tipo=tipo)
    return (i_piu - i_meno) / 10


def main():
    campo = C.campo_per_tipo()
    print(f'{"tipo":10s} {"pareggio":>10} {"atteso":>10} {"guadagno/pt":>12} {"atteso":>8}')
    tutti_ok = True
    for tipo in ('cap 260', 'cap 220', 'Uncapped', 'Beginner'):
        regole = C.REGOLE[tipo]
        av = campo.get(tipo) or []
        sigma = SIGMA_PER_TIPO[tipo]
        p = C.pareggio(av, regole['costo'], regole['premi'], sigma=sigma, tipo=tipo)
        g = guadagno_per_punto(p, av, regole['premi'], sigma, tipo)
        p_atteso, g_atteso = ATTESI[tipo]
        ok_p = abs(p - p_atteso) < 0.5
        ok_g = abs(g - g_atteso) < 0.1
        if not (ok_p and ok_g):
            tutti_ok = False
        print(f'{tipo:10s} {p:>10.2f} {p_atteso:>10.1f} {g:>12.3f} {g_atteso:>8.2f} '
              f'{"OK" if ok_p and ok_g else "SCARTO"}')
    print()
    print('TUTTI I VALORI RIPRODOTTI' if tutti_ok else 'ATTENZIONE: SCARTO, FERMARSI')


if __name__ == '__main__':
    main()
