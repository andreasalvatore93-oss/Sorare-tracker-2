# Report analisi manager — GW football-31-jul-4-aug-2026

Generato: 2026-08-04 22:50 (locale). Metodologia: analisi_manager/METODOLOGIA.md

## A. Selezione (residuo = realizzato - atteso)

- Osservazioni: **282** su 8 manager attivi. Scarti: 16 no atteso (storico/target), 12 non ha giocato (0), 2 arena esclusa (arena_altro).
- **Residuo medio (bias) = -1.50**  [>0 = battono il modello, ~0 = no segnale]
- Correlazione atteso/reale +0.227; MAE 15.7; dispersione previsto 4.8 vs reale 19.6 (4.1x compressione).
- Lift di selezione: atteso medio dei loro pick 51.8 vs slot medio 51.8 = **-0.0** punti.

### Per ruolo

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Defender | 87 | +0.4 | 17.2 | +0.02 |
| Midfielder | 79 | +1.5 | 14.5 | +0.42 |
| Forward | 59 | -3.7 | 14.2 | +0.12 |
| Goalkeeper | 57 | -6.3 | 16.7 | -0.19 |

### Per competizione

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| Cap 260 | 140 | -1.3 | 15.9 | +0.06 |
| Cap 220 | 109 | -1.7 | 15.6 | +0.30 |
| Uncapped | 18 | +1.7 | 17.4 | +0.58 |
| Beginner | 15 | -5.4 | 12.9 | +0.04 |

### Per lega (n>=15)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| mls | 131 | -2.7 | 15.2 | +0.25 |
| kleague | 34 | -1.9 | 15.6 | +0.20 |
| scozia | 23 | +7.6 | 14.2 | -0.37 |
| messico | 19 | -3.0 | 11.3 | +0.53 |
| argentina | 17 | -11.4 | 23.9 | -0.51 |

### Per fascia di atteso

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 50-55 | 107 | -1.8 | 14.5 | +0.02 |
| 45-50 | 90 | -1.3 | 15.1 | -0.32 |
| 55-60 | 57 | -4.1 | 18.6 | +0.10 |
| <45 | 19 | +0.8 | 11.6 | -0.23 |
| >=60 | 9 | +11.5 | 27.2 | +0.86 |

### Per fascia di L10

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 40-50 | 132 | -1.8 | 16.4 | -0.04 |
| 50-60 | 113 | -2.0 | 14.4 | +0.23 |
| <40 | 23 | -3.8 | 16.6 | +0.20 |
| 60-70 | 11 | +2.6 | 14.7 | +0.46 |
| >=70 | 3 | +32.2 | 32.2 | +1.00 |

### Casa/trasferta

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| True | 154 | -2.7 | 17.2 | +0.30 |
| False | 119 | +0.2 | 13.9 | +0.15 |
| None | 9 | -3.7 | 13.6 | -0.23 |

## Consenso

- A giocatore unico: n 204, bias -0.16, corr +0.222.

### Residuo per numero di manager che lo schierano

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| 1 manager | 160 | +0.5 | 14.0 | +0.23 |
| 2 manager | 37 | -1.0 | 16.7 | +0.23 |
| 3 manager | 6 | -6.5 | 18.3 | +0.64 |
| 4 manager | 1 | -40.5 | 40.5 | - |

## B. Capitano

- Formazioni con capitano valutabile: 62.
- Il loro capitano è la carta a **max atteso** della formazione: 27/62 (44%) = accordo col nostro criterio pick_captain.
- Capitano che rende **sopra la media** della sua formazione: 37/62 (60%).
- Residuo capitani +0.13 (n 58) vs non-capitani -1.92 (n 224).

## D. Esito arena (il nostro atteso-somma predice il piazzamento?)

- Formazioni complete valutabili: 61.
- Corr(atteso_somma, rank reale) = +0.114 (negativa attesa: più atteso → rank migliore).
- Corr(atteso_somma, punteggio formazione reale) = +0.008.

## Correlazioni & code

- corr(residuo, atteso) = -0.018 (se <0: sovrastimiamo gli attesi alti / sottostimiamo i bassi).
- corr(residuo, L10) = +0.050.
- corr(residuo, profondità storico) = -0.103 (se >0: giochiamo peggio con poco storico).
- boom (>75) osservati 10.6% | flop (<25) 5.0%.

### F. Skill per manager (residuo)

| gruppo | n | bias | MAE | corr |
|---|--:|--:|--:|--:|
| fins49 | 83 | +0.7 | 13.6 | +0.14 |
| milkyfresht | 62 | -5.8 | 14.9 | +0.10 |
| shirimimi | 49 | -0.5 | 17.3 | +0.28 |
| bxl-spartak | 42 | -6.5 | 14.4 | +0.20 |
| lairdinho | 25 | +3.0 | 19.9 | +0.73 |
| eoghankelly | 9 | +11.5 | 16.7 | +0.02 |
| ninoshooter | 7 | +5.4 | 21.7 | -0.55 |
| spillo678 | 5 | -6.3 | 24.3 | -0.92 |

## G. Coda positiva (dove hanno battuto di più l'atteso)

| giocatore | ruolo | lega | atteso | reale | residuo |
|---|---|---|--:|--:|--:|
| Braian Ojeda | Midfielder | mls | 47 | 100 | +53 |
| Jonathan Sirois | Goalkeeper | mls | 47 | 98 | +51 |
| Fernando Muslera | Goalkeeper | argentina | 51 | 100 | +49 |
| Lee Ju-Yong | Defender | kleague | 55 | 100 | +45 |
| Tobias Salquist | Defender | danimarca | 55 | 100 | +45 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |
| Toni Fruk | Midfielder | croazia | 57 | 100 | +43 |
| Juan Brunetta | Midfielder | messico | 59 | 100 | +41 |
| Brandon Bye | Defender | mls | 48 | 87 | +39 |
| Aaron Long | Defender | mls | 47 | 83 | +36 |
| Aaron Long | Defender | mls | 47 | 83 | +36 |
| Andres Andrade | Defender | austria | 58 | 93 | +35 |
| Andres Andrade | Defender | austria | 58 | 93 | +35 |
| Andres Andrade | Defender | austria | 58 | 93 | +35 |
| Andres Andrade | Defender | austria | 58 | 93 | +35 |

- Ruoli nella coda: {'Midfielder': 4, 'Goalkeeper': 2, 'Defender': 9}
- Leghe nella coda: {'mls': 5, 'argentina': 1, 'kleague': 1, 'danimarca': 1, 'croazia': 2, 'messico': 1, 'austria': 4}
