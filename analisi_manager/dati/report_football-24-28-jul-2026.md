# Report analisi manager — GW football-24-28-jul-2026

Generato: 2026-08-04 22:51 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **167** su 7 manager attivi. Scarti: 22 no atteso (storico/target), 1 arena esclusa (arena_altro), 1 non ha giocato (0).
- **Residuo medio (bias) = +1.60**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.199; MAE 12.7; dispersione previsto 5.0 vs reale 15.5 (3.1x compressione).
- Lift di selezione: atteso medio dei loro pick 52.1 vs slot medio 51.8 = **+0.3** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 46 | +3.0 | 9.1 | +0.36 |
| Midfielder | 44 | -1.8 | 12.7 | +0.22 |
| Forward | 39 | +0.5 | 16.0 | +0.37 |
| Goalkeeper | 38 | +4.9 | 13.9 | -0.02 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 82 | +1.9 | 14.2 | +0.19 |
| Cap 220 | 70 | +3.5 | 11.0 | +0.34 |
| Beginner | 10 | -8.2 | 11.0 | -0.01 |
| Uncapped | 5 | -9.3 | 16.4 | -0.36 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 92 | +0.8 | 13.5 | +0.11 |
| kleague | 29 | -2.4 | 11.3 | +0.02 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 61 | -1.3 | 12.4 | +0.03 |
| 45-50 | 55 | +6.4 | 12.7 | -0.12 |
| 55-60 | 33 | -0.4 | 14.3 | +0.20 |
| >=60 | 9 | +1.1 | 11.8 | -0.41 |
| <45 | 9 | -0.3 | 10.3 | +0.67 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 40-50 | 88 | +2.6 | 12.2 | +0.20 |
| 50-60 | 59 | +1.2 | 14.6 | +0.04 |
| <40 | 12 | -0.2 | 5.8 | +0.56 |
| 60-70 | 6 | -10.5 | 16.4 | +0.09 |
| >=70 | 2 | +13.4 | 13.4 | - |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 88 | +3.2 | 12.4 | +0.14 |
| False | 65 | -0.8 | 14.5 | +0.20 |
| None | 14 | +2.8 | 7.0 | +0.68 |

## Consenso

- A giocatore unico: n 131, bias +0.84, corr +0.184.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 108 | +0.6 | 13.7 | +0.20 |
| 2 manager | 20 | +0.0 | 9.9 | +0.09 |
| 3 manager | 2 | +21.2 | 21.2 | - |
| 4 manager | 1 | +0.0 | 0.0 | - |

## B. Capitano

- Formazioni con capitano valutabile: 38.
- Il loro capitano è la carta a **max atteso** della formazione: 18/38 (47%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 27/38 (71%).
- Residuo capitani +1.57 (n 30) vs non-capitani +1.60 (n 137).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 33.
- Corr(atteso_somma, rank reale) = -0.088 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.213.

## Correlazioni & code

- corr(residuo, atteso) = -0.126 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.086.
- corr(residuo, profondità storico) = +0.100 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 10.2% | flop (<25) 0.6%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| shirimimi | 40 | -0.3 | 10.6 | +0.28 |
| milkyfresht | 36 | +3.4 | 13.6 | -0.16 |
| bxl-spartak | 30 | +2.8 | 13.6 | +0.18 |
| fins49 | 26 | +3.4 | 11.7 | +0.31 |
| lairdinho | 20 | -1.5 | 15.4 | +0.04 |
| ninoshooter | 10 | -6.6 | 10.4 | +0.65 |
| eoghankelly | 5 | +16.0 | 17.1 | +0.42 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Yohei Takaoka | Goalkeeper | mls | 44 | 78 | +34 |
| Rocco Ríos Novo  | Goalkeeper | mls | 50 | 83 | +33 |
| Wesley Moraes  | Forward | cina | 54 | 84 | +30 |
| Andrés Perea | Midfielder | mls | 50 | 79 | +29 |
| Kristijan Kahlina | Goalkeeper | mls | 47 | 75 | +29 |
| Kristijan Kahlina | Goalkeeper | mls | 47 | 75 | +29 |
| Kristijan Kahlina | Goalkeeper | mls | 47 | 75 | +29 |
| Kerwin Vargas | Forward | mls | 55 | 83 | +28 |
| Axel Ojeda | Midfielder | mls | 49 | 76 | +27 |
| Warleson | Goalkeeper | brasile | 49 | 74 | +25 |
| Miguel Almirón | Forward | mls | 58 | 83 | +25 |
| Miguel Almirón | Forward | mls | 58 | 83 | +25 |
| Miguel Almirón | Forward | mls | 58 | 83 | +25 |
| Prince Ampem | Forward | cina | 48 | 73 | +25 |
| Mateusz Bogusz | Midfielder | mls | 49 | 73 | +24 |

- Ruoli nella coda: {'Goalkeeper': 6, 'Forward': 6, 'Midfielder': 3}
- Leghe nella coda: {'mls': 12, 'cina': 2, 'brasile': 1}
