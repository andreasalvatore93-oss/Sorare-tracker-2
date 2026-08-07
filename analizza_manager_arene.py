#!/usr/bin/env python3
"""Analizza i manager estratti e riporta dati arena."""
import os
import json
import sys

TIPI_VALIDI = ('arena_limited', 'arena_limited_beginner', 'arena_limited_uncapped')

def analizza_manager(slug):
    """Leggi manager_<slug>.json e conta: gw_valide, arene_valide, %beginner."""
    path = os.path.join('dati_globali', f'manager_{slug}.json')
    if not os.path.exists(path):
        return None

    with open(path, encoding='utf-8') as f:
        dati = json.load(f)

    gw_valide = 0
    arene_valide = 0
    beginner = 0
    arene_per_gw = []

    for gw, righe in (dati.get('giornate') or {}).items():
        arene_in_gw = []
        for r in righe:
            tipo = r.get('tipo_arena')
            carte = r.get('carte')
            if tipo in TIPI_VALIDI and carte:
                arene_in_gw.append(r)
                arene_valide += 1
                if tipo == 'arena_limited_beginner':
                    beginner += 1
        if arene_in_gw:
            gw_valide += 1
            arene_per_gw.append(len(arene_in_gw))

    media_arene_per_gw = sum(arene_per_gw) / len(arene_per_gw) if arene_per_gw else 0
    pct_beginner = 100 * beginner / arene_valide if arene_valide > 0 else 0

    return {
        'gw_valide': gw_valide,
        'arene_valide': arene_valide,
        'arene_per_gw': media_arene_per_gw,
        'pct_beginner': pct_beginner,
    }

if __name__ == '__main__':
    for slug in sys.argv[1:]:
        dati = analizza_manager(slug)
        if dati:
            print(f"{slug} | {dati['gw_valide']} | {dati['arene_valide']} | "
                  f"{dati['arene_per_gw']:.1f} | {dati['pct_beginner']:.0f}%")
        else:
            print(f"{slug} | FILE NON TROVATO")
