# Report analisi manager — GW football-21-24-jul-2026

Generato: 2026-08-05 00:57 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **396** su 7 manager attivi. Scarti: 24 non ha giocato (0), 5 no atteso (storico/target).
- **Residuo medio (bias) = +1.03**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.204; MAE 14.5; dispersione previsto 5.0 vs reale 18.4 (3.7x compressione).
- Lift di selezione: atteso medio dei loro pick 53.3 vs slot medio 51.8 = **+1.5** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 116 | -1.7 | 13.4 | +0.24 |
| Forward | 105 | +2.6 | 14.5 | -0.09 |
| Midfielder | 96 | +4.9 | 16.1 | +0.15 |
| Goalkeeper | 79 | -1.7 | 14.4 | -0.11 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 274 | +0.8 | 13.8 | +0.22 |
| Elite | 51 | -1.4 | 14.9 | +0.45 |
| Cap 220 | 36 | +8.5 | 15.2 | -0.08 |
| Beginner | 20 | +1.5 | 16.8 | +0.00 |
| Uncapped | 15 | -4.2 | 22.8 | +0.21 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 204 | -1.2 | 14.8 | +0.13 |
| kleague | 46 | +4.0 | 13.9 | +0.04 |
| portogallo | 25 | +5.9 | 9.1 | -0.15 |
| olanda | 22 | +6.2 | 22.5 | -0.05 |
| argentina | 16 | -4.4 | 13.3 | -0.71 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 159 | +0.1 | 12.5 | +0.23 |
| 55-60 | 96 | +3.1 | 16.7 | +0.37 |
| 45-50 | 82 | +3.1 | 12.3 | +0.22 |
| >=60 | 44 | -6.2 | 16.9 | +0.31 |
| <45 | 15 | +7.3 | 27.8 | -0.57 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 182 | +2.9 | 14.7 | +0.26 |
| 40-50 | 156 | -2.0 | 13.1 | +0.08 |
| 60-70 | 33 | +0.8 | 19.5 | -0.28 |
| <40 | 14 | +17.0 | 21.0 | -0.62 |
| >=70 | 11 | -6.6 | 10.1 | +0.37 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| False | 182 | +1.6 | 16.9 | +0.07 |
| True | 175 | -0.3 | 12.0 | +0.35 |
| None | 39 | +4.3 | 14.8 | +0.60 |

## Consenso

- A giocatore unico: n 204, bias +0.83, corr +0.264.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 126 | -0.4 | 13.4 | +0.32 |
| 2 manager | 62 | +3.0 | 16.9 | +0.30 |
| 3 manager | 13 | +1.0 | 17.1 | -0.41 |
| 4 manager | 2 | -2.4 | 5.7 | - |
| 6 manager | 1 | +22.3 | 22.3 | - |

## B. Capitano

- Formazioni con capitano valutabile: 85.
- Il loro capitano è la carta a **max atteso** della formazione: 34/85 (40%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 49/85 (58%).
- Residuo capitani +3.83 (n 77) vs non-capitani +0.36 (n 319).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 85.
- Corr(atteso_somma, rank reale) = +0.155 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = -0.107.

## Correlazioni & code

- corr(residuo, atteso) = -0.068 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.042.
- corr(residuo, profondità storico) = -0.062 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 14.9% | flop (<25) 2.5%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 227 | +0.2 | 13.5 | +0.30 |
| bxl-spartak | 78 | +3.4 | 17.4 | +0.16 |
| shirimimi | 41 | +5.2 | 16.1 | -0.03 |
| milkyfresht | 30 | -4.0 | 13.2 | -0.36 |
| eoghankelly | 10 | +2.2 | 14.8 | +0.47 |
| lairdinho | 5 | -7.6 | 15.9 | -0.53 |
| spillo678 | 5 | +4.2 | 12.5 | -0.79 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Jeong Seung-Won | Midfielder | kleague | 51 | 100 | +49 |
| Renato Steffen | Midfielder | svizzera | 55 | 98 | +43 |
| Renato Steffen | Midfielder | svizzera | 55 | 98 | +43 |
| Seo Myung-Guan | Defender | kleague | 54 | 96 | +41 |
| Seo Myung-Guan | Defender | kleague | 54 | 96 | +41 |
| Philip Billing | Midfielder | danimarca | 59 | 100 | +41 |
| Philip Billing | Midfielder | danimarca | 59 | 100 | +41 |
| Marcel Hartel | Midfielder | mls | 59 | 100 | +41 |
| Marcel Hartel | Midfielder | mls | 59 | 100 | +41 |
| Joaquín Pereyra | Midfielder | mls | 56 | 96 | +40 |
| Joaquín Pereyra | Midfielder | mls | 56 | 96 | +40 |

- Ruoli nella coda: {'Goalkeeper': 4, 'Midfielder': 9, 'Defender': 2}
- Leghe nella coda: {'mls': 8, 'kleague': 3, 'svizzera': 2, 'danimarca': 2}
