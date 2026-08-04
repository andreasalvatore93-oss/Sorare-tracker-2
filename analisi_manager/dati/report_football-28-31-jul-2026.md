# Report analisi manager — GW football-28-31-jul-2026

Generato: 2026-08-04 22:52 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **653** su 9 manager attivi. Scarti: 24 non ha giocato (0), 18 no atteso (storico/target).
- **Residuo medio (bias) = +6.35**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.103; MAE 16.5; dispersione previsto 5.0 vs reale 18.7 (3.8x compressione).
- Lift di selezione: atteso medio dei loro pick 53.3 vs slot medio 51.8 = **+1.5** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 181 | +10.6 | 16.6 | -0.13 |
| Midfielder | 178 | +5.3 | 15.9 | +0.02 |
| Forward | 159 | +6.3 | 19.2 | +0.04 |
| Goalkeeper | 135 | +2.2 | 13.9 | +0.22 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 410 | +5.2 | 16.0 | +0.05 |
| Elite | 108 | +7.7 | 17.4 | +0.16 |
| Uncapped | 86 | +10.6 | 18.3 | +0.01 |
| Beginner | 34 | +0.8 | 12.2 | +0.61 |
| Cap 220 | 15 | +15.3 | 22.6 | +0.03 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| argentina | 83 | -0.3 | 12.1 | -0.02 |
| austria | 80 | +13.6 | 19.5 | +0.66 |
| portogallo | 69 | +29.0 | 29.0 | -0.45 |
| olanda | 56 | +12.0 | 18.6 | +0.68 |
| danimarca | 55 | +2.2 | 13.8 | +0.14 |
| croazia | 53 | -6.0 | 12.1 | +0.61 |
| turchia | 50 | -1.9 | 16.5 | +0.19 |
| brasile | 47 | +2.7 | 15.1 | +0.06 |
| grecia | 42 | +1.6 | 14.9 | -0.16 |
| svizzera | 37 | +1.7 | 17.2 | +0.17 |
| germania | 31 | +9.0 | 14.2 | +1.00 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 269 | +5.7 | 16.3 | +0.28 |
| 45-50 | 170 | +11.9 | 19.1 | -0.01 |
| 55-60 | 140 | +5.9 | 15.2 | -0.07 |
| >=60 | 66 | -3.5 | 14.0 | +0.44 |
| <45 | 8 | -2.0 | 11.5 | +0.03 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 252 | +6.3 | 15.0 | +0.10 |
| 40-50 | 241 | +6.6 | 17.7 | -0.14 |
| 60-70 | 130 | +6.3 | 17.3 | +0.01 |
| <40 | 24 | +9.2 | 14.9 | +0.27 |
| >=70 | 6 | -12.4 | 20.0 | +1.00 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| False | 394 | +9.3 | 18.2 | -0.00 |
| True | 220 | +2.2 | 14.6 | +0.31 |
| None | 39 | -0.2 | 9.8 | +0.46 |

## Consenso

- A giocatore unico: n 149, bias +2.99, corr +0.172.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 78 | +4.2 | 14.5 | +0.18 |
| 2 manager | 49 | -0.4 | 15.5 | +0.18 |
| 3 manager | 17 | +1.3 | 13.1 | +0.24 |
| 4 manager | 3 | +23.2 | 23.2 | +0.37 |
| 7 manager | 1 | +51.6 | 51.6 | - |
| 5 manager | 1 | -6.6 | 6.6 | - |

## B. Capitano

- Formazioni con capitano valutabile: 139.
- Il loro capitano è la carta a **max atteso** della formazione: 64/139 (46%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 78/139 (56%).
- Residuo capitani +6.75 (n 133) vs non-capitani +6.25 (n 520).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 138.
- Corr(atteso_somma, rank reale) = +0.042 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = -0.004.

## Correlazioni & code

- corr(residuo, atteso) = -0.162 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.069.
- corr(residuo, profondità storico) = +0.244 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 25.7% | flop (<25) 0.8%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| satonio | 477 | +6.8 | 16.3 | +0.10 |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 122 | +3.4 | 16.2 | +0.20 |
| lairdinho | 17 | +6.3 | 16.8 | -0.05 |
| bxl-spartak | 10 | +18.2 | 24.3 | +0.13 |
| spillo678 | 10 | +13.1 | 22.5 | -0.08 |
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
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Clément Lenglet | Defender | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |
| Vangelis Pavlidis | Forward | portogallo | 48 | 100 | +52 |

- Ruoli nella coda: {'Defender': 9, 'Forward': 6}
- Leghe nella coda: {'portogallo': 15}
