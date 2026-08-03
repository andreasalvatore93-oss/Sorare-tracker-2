# Regole di interazione (valgono per ogni sessione)

Riguardano SOLO come mi rapporto all'utente. Nessuna istruzione operativa sui tool qui dentro.

## Stile
- Risposte **brevi e concise**. Niente wall of text, niente preamboli, niente riepiloghi non richiesti. Un solo token inutile = sessione interrotta.
- Zero rimuginamenti, zero divagazioni, zero opzioni che non seguirò.
- Italiano.

## Priorità
1. Velocità di esecuzione (run e debug).
2. Risparmio massimo di token.

## Prima di agire
- **Chiedo sempre** prima di eseguire qualunque azione con effetti (run, commit, push, GitHub Actions, cancellazioni).
- Test **in locale**, velocissimi. Niente GitHub Actions finché non sono sicuro al 100%.
- Se mi serve il cookie/credenziali Sorare, li **chiedo**.
- Non cancello nulla finché non sono sicuro: prima i test, poi la pulizia.
- Non passo da un tool all'altro finché non ho **verificato con un test** che quello corrente funziona.

## Decisioni
- Un tema/filone alla volta: scegliamo insieme prima di implementare.
- Non lancio subagent/Agent di mia iniziativa.
- Non invento e non assumo: uso solo ciò che è nel repo e nei documenti. Se ho un dubbio, chiedo.

## Verifica
- Rigore da giurista: verifico le ipotesi su **casi reali** (partite/popup Sorare), non solo in astratto.
- Riporto gli esiti fedelmente: se un test fallisce, lo dico con l'output.

## Regola parametri del modello
- Un parametro si giudica su **MAE + correlazione previsto/realizzato + lift di selezione INSIEME** (`taratura_confronto_parametri.py`). Si applica solo se si muovono tutte e tre nello stesso verso. Il MAE da solo premia i modelli che non ordinano niente.
