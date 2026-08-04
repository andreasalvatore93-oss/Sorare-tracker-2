# Report analisi manager — GW football-21-24-jul-2026

Generato: 2026-08-04 22:25 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **163** su 6 manager attivi. Scarti: 11 no atteso (storico/target), 6 non ha giocato (0).
- **Residuo medio (bias) = +2.40**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.077; MAE 16.2; dispersione previsto 5.0 vs reale 19.6 (3.9x compressione).
- Lift di selezione: atteso medio dei loro pick 53.2 vs slot medio 51.8 = **+1.4** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 48 | -2.8 | 15.0 | +0.17 |
| Forward | 45 | +4.2 | 16.2 | -0.14 |
| Midfielder | 39 | +7.1 | 16.9 | +0.14 |
| Goalkeeper | 31 | +1.8 | 17.1 | -0.45 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 94 | +1.2 | 15.2 | +0.18 |
| Cap 220 | 36 | +8.6 | 15.2 | -0.08 |
| Beginner | 18 | +1.9 | 17.9 | -0.06 |
| Uncapped | 15 | -4.2 | 22.8 | +0.21 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 86 | -0.1 | 17.1 | -0.01 |
| kleague | 26 | +5.1 | 15.7 | +0.01 |
| portogallo | 17 | +6.9 | 11.1 | -0.30 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 65 | -2.7 | 12.9 | +0.15 |
| 55-60 | 39 | +5.4 | 18.3 | +0.32 |
| 45-50 | 35 | +7.5 | 15.1 | +0.29 |
| >=60 | 18 | -5.3 | 18.3 | +0.08 |
| <45 | 6 | +31.5 | 38.2 | -0.72 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 40-50 | 71 | +0.9 | 13.7 | -0.15 |
| 50-60 | 66 | +2.3 | 16.9 | +0.21 |
| 60-70 | 13 | +4.6 | 22.8 | -0.56 |
| <40 | 10 | +15.9 | 21.6 | -0.59 |
| >=70 | 3 | -14.2 | 14.2 | -0.48 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 78 | -0.6 | 12.7 | +0.22 |
| False | 67 | +6.0 | 20.3 | -0.11 |
| None | 18 | +1.6 | 16.1 | +0.61 |

## Consenso

- A giocatore unico: n 121, bias +2.48, corr +0.182.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 98 | +3.3 | 16.7 | +0.28 |
| 2 manager | 20 | -2.1 | 16.3 | -0.31 |
| 3 manager | 2 | -2.4 | 5.7 | - |
| 5 manager | 1 | +22.3 | 22.3 | - |

## B. Capitano

- Formazioni con capitano valutabile: 36.
- Il loro capitano è la carta a **max atteso** della formazione: 16/36 (44%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 23/36 (64%).
- Residuo capitani +5.21 (n 34) vs non-capitani +1.65 (n 129).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 35.
- Corr(atteso_somma, rank reale) = +0.304 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = -0.282.

## Correlazioni & code

- corr(residuo, atteso) = -0.179 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.109.
- corr(residuo, profondità storico) = -0.032 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 17.2% | flop (<25) 2.5%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| bxl-spartak | 77 | +3.7 | 17.4 | +0.14 |
| shirimimi | 40 | +5.5 | 16.5 | -0.05 |
| milkyfresht | 28 | -4.1 | 13.6 | -0.35 |
| eoghankelly | 9 | +3.5 | 15.4 | +0.46 |
| lairdinho | 5 | -7.6 | 15.9 | -0.53 |
| spillo678 | 4 | +1.2 | 11.6 | -0.84 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Maxime Crépeau | Goalkeeper | mls | 42 | 96 | +54 |
| Jeong Seung-Won | Midfielder | kleague | 49 | 100 | +51 |
| Renato Steffen | Midfielder | svizzera | 55 | 98 | +43 |
| Seo Myung-Guan | Defender | kleague | 54 | 96 | +41 |
| Philip Billing | Midfielder | danimarca | 59 | 100 | +41 |
| Marcel Hartel | Midfielder | mls | 59 | 100 | +41 |
| Joaquín Pereyra | Midfielder | mls | 56 | 96 | +40 |
| Mika Godts | Forward | olanda | 62 | 100 | +38 |
| Davy Klaassen | Midfielder | olanda | 48 | 80 | +32 |
| Jeisson Palacios | Defender | mls | 58 | 89 | +31 |
| Matheus Oliveira | Midfielder | kleague | 60 | 89 | +30 |
| Tomas Totland | Defender | mls | 49 | 78 | +29 |
| Nicolás Fernández-Mercau | Defender | mls | 59 | 88 | +28 |

- Ruoli nella coda: {'Goalkeeper': 3, 'Midfielder': 7, 'Defender': 4, 'Forward': 1}
- Leghe nella coda: {'mls': 8, 'kleague': 3, 'svizzera': 1, 'danimarca': 1, 'olanda': 2}
