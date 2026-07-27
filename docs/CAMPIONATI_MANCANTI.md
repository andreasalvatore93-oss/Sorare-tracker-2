# Campionati mancanti — carte possedute non ancora coperte da una pipeline dedicata

Generato da `diagnostics/discover_missing_leagues.py` (run reale del 27/07/2026), fonte completa
in `diagnostics/output/missing_leagues_report.json`. Esclusi gli 8 campionati gia' coperti (MLS,
K League, Brasile, Croazia, Portogallo, Scozia, Austria, Belgio) + Spagna/Olanda (in corso di
verifica in sessione separata). **`mlspa` escluso da questa lista**: confermato dall'utente essere
un duplicato del pool MLS gia' tracciato (stesso slug MLS ma sotto una chiave diversa lato Sorare),
non un campionato realmente mancante — da verificare comunque incrociando gli slug giocatore prima
di scartarlo definitivamente (non ancora fatto).

**`__unknown__` (70 carte, 67 giocatori)**: carte con `domesticLeague` mancante/nullo nei dati
Sorare — NON e' uno slug valido, va ispezionato singolarmente (probabilmente giocatori free agent,
squadre senza campionato assegnato, o un problema di query) prima di poterci fare qualunque cosa.

## Priorita' alta (>=20 carte)

| Slug | Nome | Carte | Giocatori |
|---|---|---|---|
| `eredivisie` | Eredivisie (Olanda) | 121 | 112 |
| `laliga-es` | LaLiga (Spagna) | 113 | 108 |
| `j1-100-year-vision-league` | J1 100 Year Vision League (Giappone) | 61 | 56 |
| `spor-toto-super-lig` | Süper Lig (Turchia) | 58 | 52 |
| `bundesliga-de` | Bundesliga (Germania) | 50 | 48 |
| `premier-league-gb-eng` | Premier League (Inghilterra) | 45 | 41 |
| `ligue-1-fr` | Ligue 1 (Francia) | 41 | 39 |
| `2-bundesliga` | 2. Bundesliga (Germania) | 41 | 39 |
| `serie-a-it` | Serie A (Italia) | 40 | 36 |
| `j1-league` | J1 League (Giappone) | 27 | 23 |
| `ligue-2-fr` | Ligue 2 (Francia) | 25 | 24 |
| `football-league-championship` | Championship (Inghilterra) | 20 | 20 |

Nota: `eredivisie`/`laliga-es` hanno GIA' una pipeline (`formazione_olanda/`/`formazione_spagna/`,
sessione 27/07) — restano in questa lista solo per completezza del dato grezzo, non vanno
riaggiunte.

## Priorita' media (5-19 carte)

| Slug | Nome | Carte | Giocatori |
|---|---|---|---|
| `liga-mx` | Liga MX (Messico) | 19 | 17 |
| `superliga-dk` | Superliga (Danimarca) | 17 | 17 |
| `superliga-argentina-de-futbol` | Liga Profesional Argentina | 14 | 13 |
| `segunda-division-es` | Segunda División (Spagna) | 12 | 12 |
| `serie-b-it` | Serie B (Italia) | 10 | 10 |
| `3-liga-de` | 3. Liga (Germania) | 10 | 10 |
| `first-division-b` | Challenger Pro League (Belgio) | 6 | 6 |
| `super-league-ch` | Super League (Svizzera) | 6 | 6 |
| `pro-league` | Saudi League | 5 | 4 |
| `ekstraklasa` | Ekstraklasa (Polonia) | 5 | 5 |
| `super-league-1` | Super League 1 (Grecia) | 5 | 5 |

## Coda lunga (1-4 carte, probabilmente non prioritari)

`russian-premier-league` (4), `2-liga` (4), `primera-a` (4, Colombia), `eliteserien` (3, Norvegia),
`landesliga` (2), `primera-division-rfef` (2), `j2-league` (2), `k3-league` (2), `regionalliga-de`
(2), `primera-division-cl` (2, Cile), e altri 15 slug con 1 sola carta ciascuno (dettaglio completo
in `diagnostics/output/missing_leagues_report.json`).

## Prossimi passi

Non ancora deciso l'ordine. Candidati naturali per volume: J1 (Giappone, valuta se unire alla
pipeline K League/Asia o farne una a parte), Süper Lig, Bundesliga, Premier League, Ligue 1 —
tutti campionati "big 5"-adiacenti con abbastanza carte da giustificare una pipeline dedicata.
Prima pero': (1) verificare `mlspa` non nasconda carte MLS realmente non tracciate, (2) ispezionare
`__unknown__`.
