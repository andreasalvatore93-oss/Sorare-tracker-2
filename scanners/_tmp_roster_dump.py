"""Test temporaneo, NON parte del bot: scarica il roster completo (deduplicato,
stesso filtro L5/L10/L40 gia' usato da fetch_team_roster) delle sole squadre
Eredivisie+Belgio, per costruire l'artifact di revisione manuale blacklist.
FIX (richiesta esplicita utente): la prima versione escludeva ANCHE i
giocatori temporaneamente blacklistati per prezzo basso (TTL 2 giorni),
tagliando fuori a torto molti giocatori del roster -- ora esclude SOLO chi
e' gia' deciso permanentemente (blacklist_manuale). Da cancellare dopo l'uso."""
import sys

sys.path.insert(0, 'scanners')
import bot_profit as bp

MANUAL_BLACKLIST_MOTIVO = 'blacklist_manuale'

manual_slugs = set()
if __import__('os').path.exists(bp.LISTA_NERA_PROFIT_PATH):
    with open(bp.LISTA_NERA_PROFIT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) != 3:
                continue
            motivo, slug, _scadenza = parts
            if motivo == MANUAL_BLACKLIST_MOTIVO:
                manual_slugs.add(slug)

teams = bp.EREDIVISIE_TEAM_WHITELIST + bp.BELGIO_TEAM_WHITELIST
roster = {}
for team_slug in teams:
    for player_slug, player_name, _snapshot in bp.fetch_team_roster(team_slug):
        if player_slug in manual_slugs:
            continue
        roster.setdefault(player_slug, player_name)

print(f"TOTALE_UNICI={len(roster)}")
for slug, name in sorted(roster.items(), key=lambda kv: kv[1]):
    print(f"ROSTER_ROW|{slug}|{name}")
