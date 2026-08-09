#!/usr/bin/env python3
"""build/fiche.py — Cache niveau 2 : fiches commander consolidées.

Une fiche = data/cache/l2/commanders/<slug>.json, réconciliée par IA UNE fois, puis
réutilisée par build_one (primers) ET build_precon (évaluations). Le build ne fait que
lire/transformer — jamais d'interprétation IA au build.

Schéma (schema_version 1) :
{
  "schema_version": 1,
  "reconciled_at": "2026-08-09T...",
  "commander": {           // fiche Scryfall du général
    "name", "slug", "mana_cost", "type_line", "color_id", "power", "toughness",
    "rarity", "legality", "set_name", "img", "oracle", "keywords"
  },
  "imgs": {"Carte": "https://cards.scryfall.io/..."},
  "oracle": {"Carte": "texte oracle"},
  "card_meta": {"Carte": {"type_line", "produced_mana", "keywords"}},
  "synergy": {"Carte": 0.83},            // scores EDHREC (quand dispo)
  "plans": [                              // plans EDHREC (tags + pools HS + contenu IA)
    {"tag", "decks", "description": [...], "win": [...],
     "high_synergy": [{"name", "synergy"}], "deck_matches": [...]}
  ],
  "combos": [...],                        // combos Spellbook pertinents (format brut API)
  "hs_imgs": {"Carte": "https://..."},    // images des pools HS + pièces de combos
  "type_recs": {"Creatures": [{"name", "synergy", "img", "oracle", "type_line"}]},
  "content": {                            // textes IA spécifiques au type de rapport
    "primer": {...},                      // quick_read, plan_html, source_html, explanations...
    "eval": {...}                         // cards (deck list), verdict, structure, fillers...
  }
}

Le contenu IA est stocké en JSON structuré (markdown léger **bold**, pas de HTML) — le
build transforme (cardify, bold, mana) au rendu.
"""
import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L2_DIR = f'{BASE}/data/cache/l2/commanders'

SCHEMA_VERSION = 1

# Champs obligatoires d'une fiche valide
REQUIRED = ['commander', 'imgs', 'plans']
COMMANDER_REQUIRED = ['name', 'oracle', 'img']


def fiche_path(slug):
    return f'{L2_DIR}/{slug}.json'


def load_fiche(slug):
    """Charge la fiche L2 du commander. Retourne None si absente/invalide (jamais d'erreur)."""
    path = fiche_path(slug)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            fiche = json.load(f)
        validate(fiche)
        return fiche
    except Exception:
        return None


def validate(fiche):
    """Garde-fou : une fiche doit avoir les champs obligatoires, sinon ValueError."""
    for k in REQUIRED:
        if k not in fiche:
            raise ValueError(f'fiche L2 : champ obligatoire manquant « {k} »')
    for k in COMMANDER_REQUIRED:
        if k not in fiche.get('commander', {}):
            raise ValueError(f'fiche L2 : commander.{k} manquant')
    if not isinstance(fiche.get('imgs'), dict):
        raise ValueError('fiche L2 : imgs doit être un dict')
    if not isinstance(fiche.get('plans'), list):
        raise ValueError('fiche L2 : plans doit être une liste')
    if fiche.get('schema_version', 0) > SCHEMA_VERSION:
        raise ValueError('fiche L2 : schema_version plus récente que le build')


def save_fiche(slug, fiche):
    """Écrit la fiche (création ou mise à jour). Valide avant d'écrire."""
    validate(fiche)
    fiche['schema_version'] = SCHEMA_VERSION
    os.makedirs(L2_DIR, exist_ok=True)
    with open(fiche_path(slug), 'w', encoding='utf-8') as f:
        json.dump(fiche, f, ensure_ascii=False, indent=1)


def fiche_from_cache(slug, commander_name, l1):
    """Assemble le « squelette » d'une fiche depuis le cache L1 (aucune IA) :
    commander Scryfall + plans EDHREC (tags) + combos Spellbook. L'IA enrichit ensuite
    (descriptions, wins, explications) avant save_fiche.

    l1 = module build/fetch (injecté pour éviter les imports circulaires).
    """
    # 1. Commander Scryfall (named)
    card = l1.scryfall_named(commander_name)
    faces = card.get('card_faces') or [card]
    oracle = ' // '.join(f.get('oracle_text', '') for f in faces) or card.get('oracle_text', '')
    img = card.get('image_uris', {}).get('normal', '')
    if not img and card.get('card_faces'):
        img = card['card_faces'][0].get('image_uris', {}).get('normal', '')
    color_id = card.get('color_identity', [])
    commander = {
        'name': card.get('name', commander_name),
        'slug': slug,
        'mana_cost': card.get('mana_cost', ''),
        'type_line': card.get('type_line', ''),
        'color_id': ''.join(color_id) if isinstance(color_id, list) else str(color_id),
        'power': card.get('power', ''),
        'toughness': card.get('toughness', ''),
        'rarity': card.get('rarity', ''),
        'legality': 'legal',
        'set_name': card.get('set_name', ''),
        'img': img,
        'oracle': oracle,
        'keywords': card.get('keywords', []),
    }

    # 2. Plans EDHREC (tag_counts de la page commander)
    plans = []
    try:
        page = l1.edhrec_page(slug)
        jd = page.get('props', {}).get('pageProps', {}).get('data', {})
        tag_counts = jd.get('tag_counts', {})
        if isinstance(tag_counts, dict):
            for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
                plans.append({'tag': tag, 'decks': count, 'high_synergy': []})
    except Exception:
        pass

    # 3. Combos Spellbook (q=nom du commander)
    combos = []
    try:
        combos = l1.spellbook_combos(commander_name)
    except Exception:
        combos = []

    fiche = {
        'schema_version': SCHEMA_VERSION,
        'reconciled_at': '',
        'commander': commander,
        'imgs': {commander_name: img},
        'oracle': {commander_name: oracle},
        'card_meta': {},
        'synergy': {},
        'plans': plans,
        'combos': combos,
        'hs_imgs': {},
        'type_recs': {},
        'content': {},
    }
    return fiche
