# Aggregato cross-GW — filone smart-money

GW incluse: 4 (football-21-24-jul-2026, football-24-28-jul-2026, football-28-31-jul-2026, football-31-jul-4-aug-2026).
Osservazioni totali: 660.

## Pool complessivo

- Residuo medio (bias) = **+1.12**  (n 660, MAE 15.4, corr +0.165).

## Per ruolo (pool)

| ruolo | n | bias | corr |
|---|--:|--:|--:|
| Defender | 195 | +0.8 | 0.1 |
| Midfielder | 173 | +2.2 | 0.33 |
| Forward | 156 | +2.1 | -0.06 |
| Goalkeeper | 136 | -0.9 | -0.21 |

## Persistenza per manager (asse F — il test smart-money)

Bias per GW; 'segno stabile' = stesso verso su tutte le GW con n>=10. Un manager con bias positivo persistente è uno sharp vero.

| manager | football-21-24-jul-2026 | football-24-28-jul-2026 | football-28-31-jul-2026 | football-31-jul-4-aug-2026 | pool_n | pool_bias | segno |
|---|--:|--:|--:|--:|--:|--:|--:|
| bxl-spartak | +3.7(77) | +2.8(30) | +18.2(10) | -6.5(42) | 159 | +1.8 | misto |
| shirimimi | +5.5(40) | -0.3(40) | ·(5) | -0.5(49) | 134 | +1.7 | misto |
| milkyfresht | -4.1(28) | +3.4(36) | - | -5.8(62) | 126 | -2.8 | misto |
| fins49 | - | +3.4(26) | - | +0.7(83) | 109 | +1.3 | + |
| lairdinho | ·(5) | -1.5(20) | +5.5(15) | +3.0(25) | 65 | +1.4 | misto |
| eoghankelly | ·(9) | ·(5) | ·(4) | ·(9) | 27 | +9.7 | ? |
| ninoshooter | - | -6.6(10) | ·(2) | ·(7) | 19 | -1.0 | ? |
| spillo678 | ·(4) | - | ·(9) | ·(5) | 18 | +6.5 | ? |
| braddersfc | - | - | ·(3) | - | 3 | -3.1 | ? |

## Skill controllata per ambiente-GW (edge = residuo - media della GW)

Toglie l'effetto 'round alto/basso-scoring'. edge>0 e n grande = il manager sceglie meglio del pool di quella GW.

| manager | n | edge medio | se | edge/se |
|---|--:|--:|--:|--:|
| eoghankelly | 27 | +7.52 | 3.76 | +2.0 |
| fins49 | 109 | +2.08 | 1.63 | +1.3 |
| spillo678 | 18 | +1.18 | 5.38 | +0.2 |
| shirimimi | 134 | +0.69 | 1.60 | +0.4 |
| bxl-spartak | 159 | +0.03 | 1.53 | +0.0 |
| lairdinho | 65 | -1.17 | 2.62 | -0.4 |
| ninoshooter | 19 | -2.40 | 4.51 | -0.5 |
| milkyfresht | 126 | -3.07 | 1.47 | -2.1 |

(controllo: edge medio complessivo +0.000, deve essere ~0 per costruzione.)

## Consenso (pool, per numero di manager nella stessa GW)

| n manager | n giocatori | bias |
|---|--:|--:|
| 1 | 389 | +1.2 |
| 2 | 84 | +0.0 |
| 3 | 11 | -0.7 |
| 4 | 2 | -20.3 |
| 5 | 2 | +37.0 |
