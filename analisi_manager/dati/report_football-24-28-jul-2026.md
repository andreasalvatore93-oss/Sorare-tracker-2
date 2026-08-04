# Report analisi manager — GW football-24-28-jul-2026

Generato: 2026-08-04 22:53 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **1158** su 9 manager attivi. Scarti: 79 non ha giocato (0), 8 no atteso (storico/target), 1 arena esclusa (arena_altro).
- **Residuo medio (bias) = +0.80**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.169; MAE 14.1; dispersione previsto 5.0 vs reale 17.3 (3.4x compressione).
- Lift di selezione: atteso medio dei loro pick 53.6 vs slot medio 51.8 = **+1.8** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Midfielder | 326 | -1.4 | 14.3 | +0.05 |
| Forward | 314 | +0.5 | 15.5 | +0.49 |
| Defender | 273 | +2.8 | 11.5 | +0.18 |
| Goalkeeper | 245 | +1.8 | 15.0 | -0.16 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 868 | +0.6 | 14.5 | +0.13 |
| Elite | 114 | +1.9 | 13.7 | +0.17 |
| Cap 220 | 108 | +0.6 | 11.2 | +0.27 |
| Uncapped | 58 | +3.1 | 15.0 | -0.04 |
| Beginner | 10 | -8.2 | 11.0 | -0.01 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 589 | +2.1 | 14.2 | +0.14 |
| kleague | 113 | -4.0 | 13.0 | +0.14 |
| argentina | 87 | -0.8 | 10.1 | -0.10 |
| messico | 78 | -7.3 | 15.0 | +0.54 |
| danimarca | 58 | -5.2 | 16.2 | +0.29 |
| svizzera | 47 | +0.3 | 13.9 | +0.27 |
| norvegia | 44 | +16.1 | 17.5 | +0.52 |
| cina | 44 | +0.4 | 17.1 | -0.05 |
| brasile | 38 | -5.5 | 14.0 | +0.30 |
| russia | 27 | +12.0 | 16.2 | +0.21 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 455 | -1.2 | 13.9 | +0.01 |
| 55-60 | 307 | +2.5 | 15.8 | -0.10 |
| 45-50 | 251 | +3.1 | 13.3 | -0.01 |
| >=60 | 107 | -3.5 | 11.9 | -0.27 |
| <45 | 38 | +8.4 | 14.9 | +0.25 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 569 | -0.0 | 14.3 | +0.19 |
| 40-50 | 402 | +2.4 | 14.7 | +0.13 |
| 60-70 | 120 | -3.0 | 14.3 | -0.27 |
| <40 | 54 | +4.0 | 8.2 | +0.45 |
| >=70 | 13 | +10.6 | 13.3 | +0.81 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 727 | +1.9 | 13.9 | +0.21 |
| False | 383 | -1.1 | 15.2 | +0.03 |
| None | 48 | -0.5 | 8.4 | +0.49 |

## Consenso

- A giocatore unico: n 393, bias +0.18, corr +0.186.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 235 | +0.2 | 14.1 | +0.19 |
| 2 manager | 115 | -1.5 | 13.7 | +0.19 |
| 3 manager | 27 | +3.4 | 11.7 | +0.38 |
| 4 manager | 13 | +3.9 | 14.9 | -0.04 |
| 5 manager | 3 | +14.2 | 14.2 | +0.37 |

## B. Capitano

- Formazioni con capitano valutabile: 249.
- Il loro capitano è la carta a **max atteso** della formazione: 107/249 (43%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 119/249 (48%).
- Residuo capitani -1.36 (n 222) vs non-capitani +1.31 (n 936).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 249.
- Corr(atteso_somma, rank reale) = -0.103 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.222.

## Correlazioni & code

- corr(residuo, atteso) = -0.123 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.087.
- corr(residuo, profondità storico) = +0.076 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 12.0% | flop (<25) 1.5%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| satonio | 677 | +1.5 | 14.9 | +0.10 |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 298 | -1.3 | 12.9 | +0.27 |
| shirimimi | 40 | -0.2 | 10.7 | +0.27 |
| milkyfresht | 38 | +3.7 | 14.7 | -0.03 |
| bxl-spartak | 36 | +3.0 | 14.4 | +0.20 |
| fins49 | 34 | +2.9 | 12.0 | +0.34 |
| lairdinho | 20 | -1.6 | 15.4 | +0.04 |
| ninoshooter | 10 | -6.6 | 10.4 | +0.65 |
| eoghankelly | 5 | +16.0 | 17.1 | +0.42 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| João Victor | Defender | russia | 52 | 94 | +43 |
| Rodrigo Rey | Goalkeeper | argentina | 48 | 90 | +43 |
| Rodrigo Rey | Goalkeeper | argentina | 48 | 90 | +43 |
| Kristoffer Velde | Forward | mls | 59 | 100 | +41 |
| Tomas Totland | Defender | mls | 51 | 92 | +41 |
| Jonathan Bond | Goalkeeper | mls | 52 | 92 | +40 |
| Jonathan Bond | Goalkeeper | mls | 52 | 92 | +40 |
| Samuel Essende | Forward | svizzera | 51 | 91 | +40 |

- Ruoli nella coda: {'Midfielder': 7, 'Defender': 2, 'Goalkeeper': 4, 'Forward': 2}
- Leghe nella coda: {'norvegia': 7, 'russia': 1, 'argentina': 2, 'mls': 4, 'svizzera': 1}
