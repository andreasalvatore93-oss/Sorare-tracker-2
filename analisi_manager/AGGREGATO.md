# Aggregato cross-GW — filone smart-money

GW incluse: 8 (football-1-4-jul-2026, football-10-13-jul-2026, football-15-20-jul-2026, football-21-24-jul-2026, football-24-28-jul-2026, football-28-31-jul-2026, football-31-jul-4-aug-2026, football-5-8-jul-2026).
Osservazioni totali: 2045.

## Pool complessivo

- Residuo medio (bias) = **+0.14**  (n 2045, MAE 14.8, corr +0.253).

## Per ruolo (pool)

| ruolo | n | bias | corr |
|---|--:|--:|--:|
| Defender | 565 | -0.5 | 0.08 |
| Midfielder | 533 | +1.2 | 0.24 |
| Forward | 532 | +0.7 | 0.31 |
| Goalkeeper | 415 | -1.1 | 0.04 |

## Persistenza per manager (asse F — il test smart-money)

Bias per GW; 'segno stabile' = stesso verso su tutte le GW con n>=10. Un manager con bias positivo persistente è uno sharp vero.

| manager | football-1-4-jul-2026 | football-10-13-jul-2026 | football-15-20-jul-2026 | football-21-24-jul-2026 | football-24-28-jul-2026 | football-28-31-jul-2026 | football-31-jul-4-aug-2026 | football-5-8-jul-2026 | pool_n | pool_bias | segno |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | -6.7(44) | -1.1(65) | +1.2(169) | +0.2(227) | -1.3(298) | +3.5(122) | -0.5(306) | - | 1231 | -0.2 | misto |
| bxl-spartak | - | -2.9(19) | - | +3.4(78) | +3.0(36) | +18.2(10) | -6.0(43) | - | 186 | +1.3 | misto |
| fins49 | ·(5) | -2.4(10) | -3.2(19) | - | +2.9(34) | - | +0.7(83) | -4.7(18) | 169 | -0.1 | misto |
| shirimimi | - | - | ·(5) | +5.2(41) | -0.3(40) | ·(5) | -0.5(49) | - | 140 | +2.2 | misto |
| milkyfresht | - | - | - | -4.0(30) | +3.7(38) | - | -5.8(62) | - | 130 | -2.6 | misto |
| lairdinho | - | ·(5) | -1.3(12) | ·(5) | -1.6(20) | +6.2(17) | +1.3(28) | - | 87 | +1.4 | misto |
| eoghankelly | - | ·(5) | ·(5) | +2.2(10) | ·(5) | ·(5) | ·(9) | +2.5(15) | 54 | +4.0 | + |
| ninoshooter | - | - | - | - | -6.6(10) | ·(3) | ·(7) | ·(4) | 24 | -4.5 | ? |
| spillo678 | - | - | - | ·(5) | - | +13.1(10) | ·(5) | - | 20 | +6.0 | ? |
| braddersfc | - | - | - | - | - | ·(4) | - | - | 4 | -6.4 | ? |

## Skill controllata per ambiente-GW (edge = residuo - media della GW)

Toglie l'effetto 'round alto/basso-scoring'. edge>0 e n grande = il manager sceglie meglio del pool di quella GW.

| manager | n | edge medio | se | edge/se |
|---|--:|--:|--:|--:|
| eoghankelly | 54 | +4.45 | 2.34 | +1.9 |
| spillo678 | 20 | +3.40 | 5.13 | +0.7 |
| shirimimi | 140 | +2.04 | 1.59 | +1.3 |
| bxl-spartak | 186 | +1.00 | 1.43 | +0.7 |
| fins49 | 169 | +0.94 | 1.33 | +0.7 |
| lairdinho | 87 | +0.66 | 2.25 | +0.3 |
| qtn-d8cd72ac-240c-493c-894c-a45f5b3d151d | 1231 | -0.44 | 0.50 | -0.9 |
| milkyfresht | 130 | -2.32 | 1.49 | -1.6 |
| ninoshooter | 24 | -4.21 | 4.09 | -1.0 |

(controllo: edge medio complessivo -0.000, deve essere ~0 per costruzione.)

## Consenso (pool, per numero di manager nella stessa GW)

| n manager | n giocatori | bias |
|---|--:|--:|
| 1 | 844 | +0.0 |
| 2 | 220 | +0.5 |
| 3 | 64 | +1.1 |
| 4 | 10 | +1.5 |
| 5 | 2 | -20.3 |
| 6 | 2 | +37.0 |
