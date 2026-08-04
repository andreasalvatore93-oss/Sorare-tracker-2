# Report analisi manager — GW football-21-24-jul-2026

Generato: 2026-08-04 22:53 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **1086** su 8 manager attivi. Scarti: 57 non ha giocato (0), 17 no atteso (storico/target).
- **Residuo medio (bias) = +0.62**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.240; MAE 14.5; dispersione previsto 5.4 vs reale 18.4 (3.4x compressione).
- Lift di selezione: atteso medio dei loro pick 53.8 vs slot medio 51.8 = **+2.0** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Midfielder | 312 | +5.5 | 15.6 | +0.29 |
| Defender | 290 | -1.0 | 12.8 | +0.05 |
| Forward | 263 | -0.8 | 15.2 | -0.05 |
| Goalkeeper | 221 | -2.5 | 14.5 | -0.01 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 784 | -0.2 | 14.2 | +0.21 |
| Elite | 132 | +2.4 | 14.8 | +0.32 |
| Uncapped | 114 | +1.4 | 15.9 | +0.25 |
| Cap 220 | 36 | +8.5 | 15.2 | -0.08 |
| Beginner | 20 | +1.5 | 16.8 | +0.01 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 522 | -1.7 | 15.2 | +0.20 |
| austria | 80 | +14.9 | 20.1 | +0.56 |
| kleague | 77 | +3.0 | 13.8 | +0.19 |
| turchia | 75 | +4.0 | 10.7 | +0.72 |
| argentina | 66 | +0.2 | 7.6 | +0.08 |
| olanda | 56 | -0.6 | 20.2 | -0.18 |
| portogallo | 45 | +4.6 | 7.8 | -0.11 |
| brasile | 33 | +2.8 | 13.9 | +0.33 |
| grecia | 29 | -12.6 | 16.2 | +0.30 |
| germania | 24 | -4.9 | 5.3 | +0.99 |
| danimarca | 23 | -3.7 | 14.4 | +0.44 |
| messico | 21 | +3.7 | 19.9 | -0.36 |
| croazia | 16 | -2.8 | 11.4 | +0.71 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 417 | +0.4 | 13.0 | +0.23 |
| 55-60 | 277 | +1.8 | 15.7 | +0.29 |
| 45-50 | 220 | +2.8 | 13.8 | +0.30 |
| >=60 | 133 | -5.7 | 15.7 | +0.49 |
| <45 | 39 | +4.4 | 22.9 | -0.17 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 551 | +2.7 | 14.7 | +0.21 |
| 40-50 | 363 | -3.1 | 13.1 | +0.11 |
| 60-70 | 116 | +0.9 | 17.7 | -0.32 |
| <40 | 33 | +9.8 | 17.2 | +0.16 |
| >=70 | 23 | -4.9 | 11.6 | +0.56 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 561 | -0.7 | 12.8 | +0.32 |
| False | 429 | +2.4 | 17.3 | +0.13 |
| None | 96 | +0.5 | 12.0 | +0.62 |

## Consenso

- A giocatore unico: n 319, bias +0.23, corr +0.249.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 174 | -0.4 | 13.6 | +0.19 |
| 2 manager | 80 | +1.3 | 13.9 | +0.45 |
| 3 manager | 50 | +0.5 | 16.6 | +0.26 |
| 4 manager | 12 | -1.1 | 16.3 | -0.42 |
| 5 manager | 2 | -2.5 | 5.6 | - |
| 7 manager | 1 | +22.3 | 22.3 | - |

## B. Capitano

- Formazioni con capitano valutabile: 232.
- Il loro capitano è la carta a **max atteso** della formazione: 98/232 (42%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 131/232 (56%).
- Residuo capitani +2.79 (n 216) vs non-capitani +0.08 (n 870).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 232.
- Corr(atteso_somma, rank reale) = +0.016 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.022.

## Correlazioni & code

- corr(residuo, atteso) = -0.052 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.007.
- corr(residuo, profondità storico) = +0.081 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 14.4% | flop (<25) 2.1%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| satonio | 690 | +0.4 | 14.5 | +0.26 |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 227 | +0.2 | 13.5 | +0.30 |
| bxl-spartak | 78 | +3.4 | 17.4 | +0.16 |
| shirimimi | 41 | +5.2 | 16.1 | -0.02 |
| milkyfresht | 30 | -4.0 | 13.2 | -0.36 |
| eoghankelly | 10 | +2.2 | 14.8 | +0.47 |
| lairdinho | 5 | -7.6 | 15.9 | -0.53 |
| spillo678 | 5 | +4.1 | 12.4 | -0.81 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Jeong Seung-Won | Midfielder | kleague | 51 | 100 | +49 |
| Jeong Seung-Won | Forward | kleague | 51 | 99 | +47 |
| Jeremy Márquez | Midfielder | messico | 54 | 100 | +46 |
| Jeremy Márquez | Midfielder | messico | 54 | 100 | +46 |
| Jeremy Márquez | Midfielder | messico | 54 | 100 | +46 |
| Jeremy Márquez | Midfielder | messico | 54 | 100 | +46 |
| Jeremy Márquez | Midfielder | messico | 54 | 100 | +46 |
| Renato Steffen | Midfielder | svizzera | 55 | 98 | +43 |
| Renato Steffen | Midfielder | svizzera | 55 | 98 | +43 |
| Luka Gavran | Goalkeeper | mls | 46 | 87 | +41 |

- Ruoli nella coda: {'Goalkeeper': 6, 'Midfielder': 8, 'Forward': 1}
- Leghe nella coda: {'mls': 6, 'kleague': 2, 'messico': 5, 'svizzera': 2}
