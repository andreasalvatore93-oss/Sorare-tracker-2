#!/usr/bin/env bash
# SMOKE TEST della matrice a shard dello scouting (14/08/2026).
#
# Uso:  bash tests/smoke_scouting_shard.sh /tmp/smoke "$(pwd)"
#
# Riproduce in un repo git usa-e-getta i due step che nel workflow
# .github/workflows/scouting_gw.yml non si possono provare senza bruciare una
# run vera: "Impacchetta previsioni e cache" (job predict) e la ricomposizione
# fatta da scouting_raccogli_predict.py (job consigli).
#
# Copre i tre modi in cui si e' rotto davvero:
#   1. run 31790910888 -- tar moriva su un prediction_*.txt CANCELLATO dal
#      predict che lo sostituiva ("Cannot stat"), 8 shard su 21 rossi dopo
#      aver predetto tutto;
#   2. trovato da questo stesso test -- un `git add A B C` muore intero se un
#      solo pathspec non matcha, e col `|| true` il job consegnava zero file
#      in silenzio;
#   3. il prediction_log.json condiviso fra shard, che va FUSO e non
#      sovrascritto, altrimenti l'ultimo shard cancella le righe degli altri.
#
# Va rilanciato ogni volta che si tocca lo step "Impacchetta" o lo script di
# ricomposizione. Non tocca la rete e non tocca il repo vero.
set -u
BASE="$1"          # cartella di lavoro dello smoke test
SORGENTE="$2"      # repo vero, da cui si clona la struttura minima
rm -rf "$BASE"; mkdir -p "$BASE/repo"; cd "$BASE/repo"

git init -q .
git config user.email t@t; git config user.name t
D=formazione_mls/output/mls_mid_all
mkdir -p "$D/.game_log_cache"
# Stato di partenza: una previsione vecchia gia' committata.
echo "vecchia" > "$D/prediction_tizio_2026-08-10_073017.txt"
python -c "import json;json.dump({'tizio|d1':{'score_atteso':1,'generated_at':'2026-08-10'}},open(r'$D/prediction_log.json','w'))"
git add -A; git commit -qm base

# Ora "gira il predict": sostituisce la previsione (nuovo file + vecchio via)
rm "$D/prediction_tizio_2026-08-10_073017.txt"
echo "nuova" > "$D/prediction_tizio_2026-08-14_101500.txt"
echo "gamelog" > "$D/.game_log_cache/tizio_gamelog.json"
python -c "import json;json.dump({'tizio|d1':{'score_atteso':42,'generated_at':'2026-08-14'},'caio|d2':{'score_atteso':7,'generated_at':'2026-08-14'}},open(r'$D/prediction_log.json','w'))"

# --- LO STEP DEL WORKFLOW, copiato riga per riga ---
SHARD=6
for P in ':(glob)formazione_*/output/**/.cache/*'          ':(glob)formazione_*/output/**/.game_log_cache/*'; do
  git add -f "$P" || true
done
for P in ':(glob)formazione_*/output/**/prediction_*.txt'          ':(glob)formazione_*/output/**/prediction_log.json'          ':(glob)formazione_*/output/**/grid_search/*'; do
  git add "$P" || true
done
git diff --cached --name-only --diff-filter=ACMR > /tmp/cambiati.txt
mkdir -p .scouting_shard
git diff --cached --name-only --diff-filter=D > .scouting_shard/cancellati.txt
if [ ! -s /tmp/cambiati.txt ] && [ ! -s .scouting_shard/cancellati.txt ]; then
  echo "SMOKE: niente da consegnare -- INATTESO"; exit 1
fi
echo "SMOKE: $(wc -l < /tmp/cambiati.txt) file da consegnare, $(wc -l < .scouting_shard/cancellati.txt) da rimuovere"
tar -czf "predict-shard-${SHARD}.tgz" .scouting_shard/cancellati.txt -T /tmp/cambiati.txt
echo "SMOKE: tar uscito con $? (0 = bene)"

# --- IL JOB CHE RICOMPONE ---
mkdir -p "$BASE/art/s6" && mv "predict-shard-${SHARD}.tgz" "$BASE/art/s6/"
# Il repo di destinazione riparte dallo stato committato (come il checkout)
# reset --hard, non checkout dall'indice: il job `consigli` fa un checkout
# di main, dove la previsione VECCHIA e' ancora presente. E' proprio quel
# file che la cancellazione deve togliere.
git reset -q --hard HEAD
rm -rf .scouting_shard
git clean -qfd
python "$SORGENTE/scouting_raccogli_predict.py" "$BASE/art" --repo .

echo "--- ESITO ---"
echo "previsione nuova presente: $(test -f "$D/prediction_tizio_2026-08-14_101500.txt" && echo SI || echo NO)"
echo "previsione vecchia rimossa: $(test -f "$D/prediction_tizio_2026-08-10_073017.txt" && echo 'NO (ancora li)' || echo SI)"
echo "cache game-log arrivata:   $(test -f "$D/.game_log_cache/tizio_gamelog.json" && echo SI || echo NO)"
echo "file di servizio NON copiato: $(test -d .scouting_shard && echo 'NO (copiato)' || echo SI)"
python -c "
import json;d=json.load(open(r'$D/prediction_log.json'))
print('prediction_log fuso:', d)
"
