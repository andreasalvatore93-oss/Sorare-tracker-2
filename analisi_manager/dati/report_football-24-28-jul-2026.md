# Report analisi manager — GW football-24-28-jul-2026

Generato: 2026-08-05 00:56 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **481** su 8 manager attivi. Scarti: 25 non ha giocato (0), 4 no atteso (storico/target), 1 arena esclusa (arena_altro).
- **Residuo medio (bias) = -0.14**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.247; MAE 13.0; dispersione previsto 4.8 vs reale 16.4 (3.4x compressione).
- Lift di selezione: atteso medio dei loro pick 52.6 vs slot medio 51.8 = **+0.8** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 128 | +2.1 | 10.4 | +0.15 |
| Midfielder | 126 | +0.0 | 13.3 | +0.25 |
| Forward | 126 | -3.8 | 14.9 | +0.53 |
| Goalkeeper | 101 | +1.3 | 13.5 | -0.15 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 281 | -0.2 | 13.9 | +0.22 |
| Cap 220 | 108 | +0.6 | 11.2 | +0.27 |
| Elite | 77 | +0.6 | 12.4 | +0.27 |
| Beginner | 10 | -8.2 | 11.0 | -0.01 |
| Uncapped | 5 | -9.3 | 16.4 | -0.36 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 215 | +0.0 | 13.4 | +0.11 |
| kleague | 62 | -3.6 | 12.3 | -0.01 |
| messico | 42 | -9.2 | 13.6 | +0.46 |
| brasile | 31 | -2.9 | 12.7 | +0.36 |
| argentina | 31 | -0.6 | 8.1 | +0.41 |
| cina | 26 | +3.6 | 16.3 | +0.08 |
| danimarca | 20 | +2.3 | 13.9 | +0.43 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 202 | -3.4 | 12.9 | +0.06 |
| 45-50 | 133 | +2.4 | 12.6 | +0.05 |
| 55-60 | 97 | +1.9 | 14.8 | +0.01 |
| >=60 | 32 | +1.2 | 10.2 | -0.32 |
| <45 | 17 | +4.6 | 12.8 | +0.14 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 229 | +0.4 | 13.6 | +0.17 |
| 40-50 | 194 | -0.9 | 12.6 | +0.28 |
| 60-70 | 30 | -3.5 | 15.4 | +0.05 |
| <40 | 25 | +4.1 | 7.8 | +0.17 |
| >=70 | 3 | +3.1 | 14.8 | +0.94 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 252 | +1.0 | 12.7 | +0.33 |
| False | 201 | -1.5 | 14.2 | +0.09 |
| None | 28 | -0.4 | 7.7 | +0.65 |

## Consenso

- A giocatore unico: n 266, bias -0.04, corr +0.203.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 198 | -0.7 | 13.6 | +0.22 |
| 2 manager | 47 | +0.9 | 12.3 | +0.16 |
| 3 manager | 18 | +2.0 | 12.7 | +0.20 |
| 4 manager | 2 | +21.2 | 21.2 | - |
| 5 manager | 1 | +0.0 | 0.0 | - |

## B. Capitano

- Formazioni con capitano valutabile: 102.
- Il loro capitano è la carta a **max atteso** della formazione: 39/102 (38%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 53/102 (52%).
- Residuo capitani -0.72 (n 93) vs non-capitani -0.00 (n 388).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 102.
- Corr(atteso_somma, rank reale) = +0.064 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.062.

## Correlazioni & code

- corr(residuo, atteso) = -0.049 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.071.
- corr(residuo, profondità storico) = +0.008 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 8.9% | flop (<25) 2.9%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 298 | -1.3 | 12.9 | +0.27 |
| shirimimi | 40 | -0.3 | 10.6 | +0.28 |
| milkyfresht | 38 | +3.7 | 14.7 | -0.03 |
| bxl-spartak | 36 | +3.0 | 14.4 | +0.20 |
| fins49 | 34 | +2.9 | 12.0 | +0.35 |
| lairdinho | 20 | -1.6 | 15.4 | +0.04 |
| ninoshooter | 10 | -6.6 | 10.4 | +0.65 |
| eoghankelly | 5 | +16.0 | 17.1 | +0.42 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| Ole Selnæs | Midfielder | norvegia | 55 | 100 | +45 |
| João Victor | Defender | russia | 52 | 94 | +43 |
| Kristoffer Velde | Forward | mls | 59 | 100 | +41 |
| Tomas Totland | Defender | mls | 51 | 92 | +41 |
| Egor Sorokin | Defender | cina | 57 | 91 | +34 |
| Egor Sorokin | Defender | cina | 57 | 91 | +34 |
| Yohei Takaoka | Goalkeeper | mls | 44 | 78 | +34 |
| Yohei Takaoka | Goalkeeper | mls | 44 | 78 | +34 |
| Yohei Takaoka | Goalkeeper | mls | 44 | 78 | +34 |
| Rocco Ríos Novo  | Goalkeeper | mls | 50 | 83 | +33 |
| Wesley Moraes  | Forward | cina | 54 | 84 | +30 |
| Wesley Moraes  | Forward | cina | 54 | 84 | +30 |
| Wesley Moraes  | Forward | cina | 54 | 84 | +30 |

- Ruoli nella coda: {'Midfielder': 3, 'Defender': 4, 'Forward': 4, 'Goalkeeper': 4}
- Leghe nella coda: {'norvegia': 3, 'russia': 1, 'mls': 6, 'cina': 5}
