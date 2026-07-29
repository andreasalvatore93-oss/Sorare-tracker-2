"""Test temporaneo, NON parte del bot: scarica il roster completo (deduplicato,
stesso filtro L5/L10/L40 gia' usato da fetch_team_roster) delle sole squadre
Eredivisie+Belgio, per costruire l'artifact di revisione manuale blacklist.
Da cancellare dopo l'uso."""
import sys

sys.path.insert(0, 'scanners')
import bot_profit as bp

teams = bp.EREDIVISIE_TEAM_WHITELIST + bp.BELGIO_TEAM_WHITELIST
roster = {}
for team_slug in teams:
    for player_slug, player_name, _snapshot in bp.fetch_team_roster(team_slug):
        if bp.is_player_blacklisted(player_slug):
            continue
        roster.setdefault(player_slug, player_name)

print(f"TOTALE_UNICI={len(roster)}")
for slug, name in sorted(roster.items(), key=lambda kv: kv[1]):
    print(f"ROSTER_ROW|{slug}|{name}")
