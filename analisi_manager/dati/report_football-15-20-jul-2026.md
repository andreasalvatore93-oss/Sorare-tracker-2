# Report analisi manager — GW football-15-20-jul-2026

Generato: 2026-08-04 23:11 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **210** su 5 manager attivi. Scarti: 12 no atteso (storico/target), 8 non ha giocato (0).
- **Residuo medio (bias) = +0.77**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.442; MAE 14.5; dispersione previsto 6.8 vs reale 19.5 (2.9x compressione).
- Lift di selezione: atteso medio dei loro pick 53.7 vs slot medio 51.8 = **+1.9** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Forward | 63 | +5.2 | 14.9 | +0.50 |
| Midfielder | 56 | +1.0 | 12.2 | +0.30 |
| Defender | 49 | -1.7 | 14.8 | +0.13 |
| Goalkeeper | 42 | -3.4 | 16.8 | +0.01 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 107 | +0.7 | 13.6 | +0.29 |
| Elite | 72 | +0.0 | 16.4 | +0.50 |
| Uncapped | 22 | +2.8 | 13.9 | +0.61 |
| Cap 220 | 9 | +2.2 | 12.4 | +0.82 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 70 | +2.3 | 15.0 | +0.61 |
| kleague | 35 | +0.5 | 13.8 | +0.32 |
| messico | 26 | -7.2 | 16.7 | +0.52 |
| cina | 16 | -7.0 | 10.5 | -0.10 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 79 | +2.0 | 13.1 | +0.15 |
| 55-60 | 49 | +2.9 | 13.5 | +0.51 |
| 45-50 | 37 | -3.5 | 19.0 | -0.15 |
| >=60 | 27 | -1.1 | 17.6 | +0.67 |
| <45 | 18 | +0.9 | 9.8 | +0.58 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 98 | -0.4 | 12.9 | +0.09 |
| 40-50 | 64 | -0.6 | 15.4 | +0.32 |
| 60-70 | 36 | +4.1 | 17.5 | -0.02 |
| <40 | 7 | -1.4 | 10.6 | +0.29 |
| >=70 | 5 | +20.2 | 20.2 | - |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 89 | +0.4 | 14.6 | +0.58 |
| False | 82 | -0.7 | 13.7 | +0.39 |
| None | 39 | +4.7 | 16.2 | +0.03 |

## Consenso

- A giocatore unico: n 119, bias +1.29, corr +0.330.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 102 | +1.8 | 14.3 | +0.34 |
| 2 manager | 17 | -1.9 | 15.3 | +0.24 |

## B. Capitano

- Formazioni con capitano valutabile: 46.
- Il loro capitano è la carta a **max atteso** della formazione: 19/46 (41%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 28/46 (61%).
- Residuo capitani +6.19 (n 41) vs non-capitani -0.55 (n 169).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 44.
- Corr(atteso_somma, rank reale) = -0.392 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.477.

## Correlazioni & code

- corr(residuo, atteso) = +0.105 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = +0.180.
- corr(residuo, profondità storico) = +0.038 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 20.5% | flop (<25) 3.8%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 169 | +1.2 | 14.1 | +0.46 |
| fins49 | 19 | -3.2 | 14.1 | +0.65 |
| lairdinho | 12 | -1.3 | 16.7 | +0.06 |
| eoghankelly | 5 | -8.3 | 16.5 | +0.42 |
| shirimimi | 5 | +15.7 | 22.9 | +0.03 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Lee You-Hyeon | Midfielder | kleague | 52 | 96 | +43 |
| Hassani Dotson | Midfielder | mls | 48 | 85 | +38 |
| Kim Dong-Hyun | Goalkeeper | kleague | 50 | 85 | +36 |
| Julián Carranza | Forward | mls | 48 | 82 | +33 |
| Unai Simón | Goalkeeper | spagna | 47 | 80 | +33 |
| Unai Simón | Goalkeeper | spagna | 47 | 80 | +33 |
| Pedro Porro | Defender | inghilterra | 53 | 85 | +32 |
| Pedro Porro | Defender | inghilterra | 53 | 85 | +32 |
| Denis Bouanga | Forward | mls | 53 | 83 | +30 |
| Denis Bouanga | Forward | mls | 53 | 83 | +30 |
| Brian Schwake | Goalkeeper | mls | 52 | 82 | +30 |
| Gustavo | Forward | kleague | 54 | 83 | +30 |
| Mark Delgado | Midfielder | mls | 59 | 88 | +29 |
| Lee Myung-Jae | Defender | kleague | 55 | 84 | +29 |
| Lee Myung-Jae | Defender | kleague | 55 | 84 | +29 |

- Ruoli nella coda: {'Midfielder': 3, 'Goalkeeper': 4, 'Forward': 4, 'Defender': 4}
- Leghe nella coda: {'kleague': 5, 'mls': 6, 'spagna': 2, 'inghilterra': 2}
