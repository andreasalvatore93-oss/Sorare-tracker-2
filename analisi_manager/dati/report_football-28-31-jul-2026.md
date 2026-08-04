# Report analisi manager — GW football-28-31-jul-2026

Generato: 2026-08-04 22:23 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **48** su 7 manager attivi. Scarti: 11 no atteso (storico/target), 1 non ha giocato (0).
- **Residuo medio (bias) = +10.47**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale -0.094; MAE 19.7; dispersione previsto 5.9 vs reale 21.5 (3.7x compressione).
- Lift di selezione: atteso medio dei loro pick 53.2 vs slot medio 51.8 = **+1.4** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 14 | +8.9 | 17.1 | -0.22 |
| Forward | 13 | +25.2 | 33.5 | -0.68 |
| Midfielder | 11 | +5.2 | 10.8 | +0.36 |
| Goalkeeper | 10 | -0.7 | 15.0 | +0.02 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 31 | +8.5 | 18.5 | -0.10 |
| Cap 220 | 15 | +15.3 | 22.6 | +0.02 |
| Beginner | 2 | +4.6 | 15.5 | - |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 45-50 | 19 | +22.8 | 27.6 | +0.15 |
| 50-55 | 14 | +6.5 | 19.7 | -0.08 |
| 55-60 | 8 | -2.9 | 10.7 | +0.66 |
| >=60 | 7 | +0.4 | 8.2 | +0.65 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 40-50 | 27 | +16.0 | 26.0 | -0.31 |
| 50-60 | 12 | +1.0 | 11.1 | +0.15 |
| 60-70 | 5 | +3.8 | 14.0 | +0.50 |
| <40 | 4 | +9.7 | 9.7 | +1.00 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| False | 34 | +18.2 | 23.8 | -0.12 |
| True | 12 | -10.2 | 10.2 | +0.77 |
| None | 2 | +3.2 | 6.8 | - |

## Consenso

- A giocatore unico: n 32, bias +4.20, corr +0.087.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 23 | +0.4 | 15.6 | +0.13 |
| 2 manager | 7 | +11.4 | 14.0 | +0.23 |
| 5 manager | 1 | +51.6 | 51.6 | - |
| 3 manager | 1 | -6.6 | 6.6 | - |

## B. Capitano

- Formazioni con capitano valutabile: 12.
- Il loro capitano è la carta a **max atteso** della formazione: 5/12 (42%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 9/12 (75%).
- Residuo capitani +16.89 (n 9) vs non-capitani +8.99 (n 39).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 9.
- Corr(atteso_somma, rank reale) = -0.055 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = -0.187.

## Correlazioni & code

- corr(residuo, atteso) = -0.346 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.294.
- corr(residuo, profondità storico) = +0.419 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 33.3% | flop (<25) 0.0%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| lairdinho | 15 | +5.5 | 17.0 | -0.10 |
| bxl-spartak | 10 | +18.2 | 24.3 | +0.13 |
| spillo678 | 9 | +16.0 | 23.5 | -0.16 |
| shirimimi | 5 | +9.6 | 19.3 | -0.11 |
| eoghankelly | 4 | +11.5 | 20.0 | -0.06 |
| braddersfc | 3 | -3.1 | 8.8 | +0.50 |
| ninoshooter | 2 | +4.6 | 15.5 | - |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Milan Škriniar | Defender | turchia | 52 | 87 | +35 |
| Milan Škriniar | Defender | turchia | 52 | 87 | +35 |
| Samuel Dahl | Defender | portogallo | 53 | 84 | +31 |
| Tobias Salquist | Defender | danimarca | 52 | 83 | +31 |
| Reinhold Ranftl | Midfielder | austria | 49 | 79 | +30 |
| Facundo Cambeses | Goalkeeper | argentina | 54 | 79 | +25 |
| Anatolii Trubin | Goalkeeper | portogallo | 46 | 69 | +23 |
| Anatolii Trubin | Goalkeeper | portogallo | 46 | 69 | +23 |

- Ruoli nella coda: {'Forward': 7, 'Defender': 4, 'Midfielder': 1, 'Goalkeeper': 3}
- Leghe nella coda: {'portogallo': 10, 'turchia': 2, 'danimarca': 1, 'austria': 1, 'argentina': 1}
