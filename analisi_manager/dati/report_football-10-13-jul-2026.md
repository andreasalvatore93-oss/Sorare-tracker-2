# Report analisi manager — GW football-10-13-jul-2026

Generato: 2026-08-04 23:12 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **104** su 5 manager attivi. Scarti: 11 non ha giocato (0).
- **Residuo medio (bias) = -1.31**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.259; MAE 14.5; dispersione previsto 5.8 vs reale 17.8 (3.1x compressione).
- Lift di selezione: atteso medio dei loro pick 55.9 vs slot medio 51.8 = **+4.1** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Forward | 31 | +1.8 | 13.8 | +0.47 |
| Midfielder | 29 | -5.1 | 14.8 | +0.13 |
| Defender | 24 | -6.6 | 13.9 | +0.02 |
| Goalkeeper | 20 | +5.6 | 15.5 | +0.04 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Uncapped | 69 | +0.3 | 13.5 | +0.32 |
| Elite | 25 | -1.9 | 17.1 | -0.20 |
| Cap 260 | 10 | -10.9 | 14.3 | +0.56 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| kleague | 30 | +6.1 | 17.3 | -0.15 |
| inghilterra | 25 | -5.5 | 10.0 | -0.01 |
| spagna | 15 | +3.4 | 13.2 | +0.57 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 40 | +0.0 | 11.0 | +0.26 |
| 55-60 | 32 | -4.5 | 15.9 | -0.55 |
| >=60 | 19 | -4.1 | 17.8 | +0.75 |
| 45-50 | 13 | +6.5 | 16.6 | +0.21 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-60 | 43 | -0.4 | 11.8 | +0.32 |
| 60-70 | 39 | -8.6 | 16.6 | -0.04 |
| 40-50 | 19 | +7.8 | 14.9 | +0.25 |
| >=70 | 3 | +22.7 | 22.7 | - |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 51 | -0.4 | 17.5 | +0.38 |
| None | 30 | -2.8 | 9.3 | +0.11 |
| False | 23 | -1.3 | 14.5 | -0.55 |

## Consenso

- A giocatore unico: n 62, bias -2.16, corr +0.193.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 47 | -3.2 | 14.0 | -0.04 |
| 2 manager | 10 | +1.7 | 15.3 | -0.53 |
| 3 manager | 5 | -0.5 | 17.8 | +0.94 |

## B. Capitano

- Formazioni con capitano valutabile: 23.
- Il loro capitano è la carta a **max atteso** della formazione: 9/23 (39%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 11/23 (48%).
- Residuo capitani -0.67 (n 20) vs non-capitani -1.46 (n 84).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 23.
- Corr(atteso_somma, rank reale) = -0.588 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.458.

## Correlazioni & code

- corr(residuo, atteso) = -0.070 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = -0.031.
- corr(residuo, profondità storico) = -0.022 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 10.6% | flop (<25) 1.9%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 65 | -1.1 | 14.4 | +0.09 |
| bxl-spartak | 19 | -2.9 | 14.7 | +0.45 |
| fins49 | 10 | -2.4 | 13.5 | -0.28 |
| eoghankelly | 5 | -9.6 | 9.6 | +0.79 |
| lairdinho | 5 | +13.1 | 20.9 | +0.62 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Zeca | Forward | kleague | 55 | 100 | +45 |
| Zeca | Forward | kleague | 55 | 100 | +45 |
| Kim Jeong-Hoon | Goalkeeper | kleague | 49 | 84 | +35 |
| Ousmane Dembélé | Forward | francia | 58 | 83 | +25 |
| Kim Dong-Jun | Goalkeeper | kleague | 47 | 71 | +24 |
| Kim Dong-Jun | Goalkeeper | kleague | 47 | 71 | +24 |
| Kim Dong-Jun | Goalkeeper | kleague | 47 | 71 | +24 |
| Kim Dong-Jun | Goalkeeper | kleague | 47 | 71 | +24 |
| Lionel Messi | Forward | mls | 77 | 100 | +23 |
| Lionel Messi | Forward | mls | 77 | 100 | +23 |
| Lionel Messi | Forward | mls | 77 | 100 | +23 |
| Bjørn Utvik | Defender | norvegia | 53 | 74 | +21 |
| Ole Selnæs | Midfielder | norvegia | 57 | 78 | +21 |
| Jude Bellingham | Midfielder | spagna | 64 | 84 | +21 |
| Jude Bellingham | Midfielder | spagna | 64 | 84 | +21 |

- Ruoli nella coda: {'Forward': 6, 'Goalkeeper': 5, 'Defender': 1, 'Midfielder': 3}
- Leghe nella coda: {'kleague': 7, 'francia': 1, 'mls': 3, 'norvegia': 2, 'spagna': 2}
