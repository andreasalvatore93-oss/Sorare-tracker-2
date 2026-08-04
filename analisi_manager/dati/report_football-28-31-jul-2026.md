# Report analisi manager — GW football-28-31-jul-2026

Generato: 2026-08-05 00:56 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **176** su 8 manager attivi. Scarti: 13 non ha giocato (0), 6 no atteso (storico/target).
- **Residuo medio (bias) = +5.24**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.109; MAE 17.1; dispersione previsto 5.8 vs reale 20.3 (3.5x compressione).
- Lift di selezione: atteso medio dei loro pick 53.5 vs slot medio 51.8 = **+1.7** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 56 | +5.5 | 15.6 | -0.09 |
| Forward | 44 | +9.6 | 23.2 | -0.14 |
| Midfielder | 39 | +2.1 | 15.1 | +0.20 |
| Goalkeeper | 37 | +3.0 | 13.9 | +0.19 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 83 | +4.6 | 16.4 | +0.03 |
| Elite | 44 | +6.4 | 20.0 | -0.06 |
| Beginner | 34 | +0.8 | 12.3 | +0.61 |
| Cap 220 | 15 | +15.3 | 22.6 | +0.02 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| argentina | 35 | -4.7 | 9.9 | +0.12 |
| turchia | 23 | +5.4 | 17.1 | +0.33 |
| portogallo | 20 | +37.2 | 37.2 | -0.29 |
| brasile | 20 | +0.9 | 18.5 | -0.34 |
| danimarca | 18 | +2.2 | 15.0 | +0.21 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 68 | +3.8 | 16.2 | +0.41 |
| 45-50 | 48 | +14.7 | 22.2 | +0.09 |
| 55-60 | 30 | -1.7 | 11.6 | +0.35 |
| >=60 | 27 | -0.7 | 17.1 | +0.52 |
| <45 | 3 | +8.4 | 8.4 | +1.00 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 40-50 | 76 | +9.8 | 19.9 | -0.12 |
| 50-60 | 59 | -0.1 | 13.4 | +0.26 |
| 60-70 | 32 | +3.6 | 18.5 | +0.14 |
| <40 | 7 | +8.7 | 8.7 | +0.93 |
| >=70 | 2 | +1.7 | 21.2 | - |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| False | 111 | +10.3 | 19.8 | +0.04 |
| True | 50 | -4.0 | 13.0 | +0.50 |
| None | 15 | -1.3 | 9.8 | +0.27 |

## Consenso

- A giocatore unico: n 93, bias +1.65, corr +0.184.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 69 | +0.2 | 15.9 | +0.20 |
| 2 manager | 18 | +0.8 | 12.9 | +0.22 |
| 3 manager | 4 | +19.6 | 19.6 | +0.39 |
| 6 manager | 1 | +51.6 | 51.6 | - |
| 4 manager | 1 | -6.6 | 6.6 | - |

## B. Capitano

- Formazioni con capitano valutabile: 39.
- Il loro capitano è la carta a **max atteso** della formazione: 18/39 (46%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 24/39 (62%).
- Residuo capitani +8.28 (n 37) vs non-capitani +4.43 (n 139).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 38.
- Corr(atteso_somma, rank reale) = -0.058 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.059.

## Correlazioni & code

- corr(residuo, atteso) = -0.173 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.159.
- corr(residuo, profondità storico) = +0.255 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 26.7% | flop (<25) 0.6%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 122 | +3.5 | 16.2 | +0.19 |
| lairdinho | 17 | +6.2 | 16.9 | -0.07 |
| bxl-spartak | 10 | +18.2 | 24.3 | +0.13 |
| spillo678 | 10 | +13.1 | 22.4 | -0.08 |
| eoghankelly | 5 | +12.2 | 19.0 | -0.06 |
| shirimimi | 5 | +9.6 | 19.3 | -0.11 |
| braddersfc | 4 | -6.4 | 9.6 | +0.75 |
| ninoshooter | 3 | -0.8 | 14.2 | -0.44 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Gerson | Midfielder | brasile | 49 | 88 | +39 |
| Milan Škriniar | Defender | turchia | 52 | 87 | +35 |
| Milan Škriniar | Defender | turchia | 52 | 87 | +35 |
| Milan Škriniar | Defender | turchia | 52 | 87 | +35 |

- Ruoli nella coda: {'Defender': 6, 'Forward': 8, 'Midfielder': 1}
- Leghe nella coda: {'portogallo': 11, 'brasile': 1, 'turchia': 3}
