#!/usr/bin/env python3
"""Moteur d'assignation Oracle→rôles (reference: role-grouping.md).

8 rôles, ordre d'affichage : Engines → Wincons → Flex → Card Advantage → Ramp → Wipes →
Interaction → Lands. Évalue les signaux dans l'ordre de priorité documenté ; premier match gagne.
"""
import re

# Ordre d'affichage (positions) — les 8 rôles
ROLE_ORDER = ['Engines', 'Wincons', 'Flex', 'CardAdvantage', 'Ramp', 'Wipes', 'Interaction', 'Lands']

ROLE_TITLES = {
    'Engines': '⚙️ Engines / Synergies',
    'Wincons': '🏆 Wincons / Finisseurs',
    'Flex': '🎯 Flex / Slots personnels',
    'CardAdvantage': '🔍 Card Advantage / Pioche',
    'Ramp': '⚡ Ramp / Accélération',
    'Wipes': '💥 Board Wipes',
    'Interaction': '🛡️ Interaction / Removal',
    'Lands': '🌲 Lands / Mana Base',
}

ROLE_SYNOPSES = {
    'Engines': 'The Plan-A core: repeatable engines tied to the commander.',
    'Wincons': 'Combo pieces, finishers and game-closing beats.',
    'Flex': 'Pet cards, off-role picks and personal slots.',
    'CardAdvantage': 'Draw engines, cantrips and tutors.',
    'Ramp': 'Mana rocks, dorks, land-search spells, treasures, cost reduction.',
    'Wipes': 'Global resets: destroy/exile/bounce all.',
    'Interaction': 'Targeted removal, counterspells and cheap protection.',
    'Lands': 'The mana base: basics, fixing and justified utility lands.',
}

# Patterns Oracle → rôle. Évalués dans CET ordre (priorité décroissante).
# Chaque entrée : (nom, regex, rôle, condition_supplémentaire optionnelle)
def _rx(*parts):
    return re.compile(r'(?:' + r')|(?:'.join(parts) + r')', re.I)

PATTERNS = [
    # --- Wincons (avant Engine — conflit règle 3) ---
    ('win_game', r'you win the game', 'Wincons'),
    ('overrun', r'creatures you control get \+X/\+X|get \+X/\+X until end of turn', 'Wincons'),
    ('mass_drain', r'each opponent loses (?!1 life)(?:\d*|x|life equal to)', 'Wincons'),
    ('big_token_army', r'create a number of .* tokens? equal to|create x .* tokens?', 'Wincons'),
    ('free_cast', r'without paying their mana costs|without paying its mana cost|may cast spells from among them', 'Wincons'),
    # --- Engines (avant CardAdvantage — conflit règle 4) ---
    ('upkeep_engine', r'at the beginning of your upkeep', 'Engines'),
    ('mechanic_engine', r'constellation|magecraft|prowess|landfall|historic', 'Engines'),
    # --- Wipes (avant Interaction — conflit règle 2) ---
    ('wipe_all', r'destroy all|exile all|put all .* on the bottom|return all .* to their owners\' hands', 'Wipes'),
    ('wipe_each', r'each (?:creature|nonland|noncreature) .* (?:deals|gets|-\d)|(?:deals|gets) .* to each (?:creature|nonland|noncreature)', 'Wipes'),
    # --- Tutors (avant CardAdvantage — conflit règle 5) ---
    ('tutor', r'search your library for a (?!basic land|land card|forest|island|swamp|mountain|plains)', 'CardAdvantage'),
    # --- Engines de doublage (avant Interaction — un doublage de jetons n'est pas du removal) ---
    ('doubling', r'twice that many|double the number of tokens|two of those tokens', 'Engines'),
    # --- Interaction ---
    ('destroy_target', r'destroy target', 'Interaction'),
    ('exile_target', r'exile target', 'Interaction'),
    ('counter_target', r'counter target', 'Interaction'),
    ('bounce_target', r'return target .* to (?:its|their) owner', 'Interaction'),
    ('redirect', r'change the target of target spell', 'Interaction'),
    ('protection', r'protection from|hexproof and indestructible until end of turn|haste and shroud', 'Interaction'),
    ('control_theft', r'gain control of target', 'Interaction'),
    ('tap_down', r'tap target|can\'t be blocked this turn', 'Interaction'),
    # --- Ramp ---
    ('ramp_search', r'search your library for a (?:basic land|land card|forest|island|swamp|mountain|plains)',
     'Ramp', lambda m, kw: True),
    ('ramp_treasure', r'create .*treasure|create .*gold token', 'Ramp'),
    ('ramp_cost', r'costs? \{.*\} less to cast', 'Ramp'),
    ('ramp_add', r'\{t\}: add|add an amount of', 'Ramp'),
    # --- Card Advantage (fallback pioche) ---
    ('draw', r'draw a card|draw two cards|draw three cards|draw x cards|you may draw|whenever .* draw a card', 'CardAdvantage'),
    ('scry_top', r'scry|look at the top|investigat', 'CardAdvantage'),
    # --- Engines de doublage (fin de liste — avant fallback) ---
    ('doubling', r'twice that many|double the number of tokens|two of those tokens', 'Engines'),
]


def assign_role(name, meta=None, oracle_text='', is_engine_hint=False, is_combo_piece=False,
                overrides=None):
    """Assigne un rôle à une carte.

    meta : dict Scryfall {type_line, produced_mana, keywords} (optionnel mais recommandé).
    overrides : dict {nom_carte: rôle} — priorité maximale (mapping manuel éditable).
    """
    if overrides and name in overrides:
        return overrides[name]

    meta = meta or {}
    type_line = meta.get('type_line', '')
    produced = meta.get('produced_mana') or []

    # 1. Signaux durs : Lands
    if 'Land' in type_line:
        return 'Lands'

    # 2. produced_mana → Ramp (dorks/rocs)
    if produced:
        if 'Creature' in type_line or 'Artifact' in type_line:
            return 'Ramp'

    # 3. Signaux contextuels (conflits 3 & 4 : Wincon avant Engine avant patterns)
    #    Nuance : une carte du pool High Synergy (engine du plan) qui apparaît aussi dans
    #    un combo reste ENGINE — le combo est documenté dans la section combos, pas son rôle.
    if is_combo_piece and not is_engine_hint:
        return 'Wincons'
    if is_engine_hint and re.search(r'whenever|at the beginning of your upkeep', oracle_text, re.I):
        return 'Engines'

    # 4. Patterns Oracle dans l'ordre de priorité
    for pat_name, pattern, role, *cond in PATTERNS:
        if re.search(pattern, oracle_text, re.I):
            if cond and not cond[0](oracle_text, None):
                continue
            return role

    # 5. Fallback
    return 'Flex'


def group_by_role(cards, overrides=None):
    """cards : liste de dicts {name, meta, oracle, is_engine_hint, is_combo_piece, ...}.
    Retourne {rôle: [cartes...]} dans l'ordre d'affichage.
    """
    grouped = {r: [] for r in ROLE_ORDER}
    for c in cards:
        role = assign_role(c.get('name', ''), c.get('meta'), c.get('oracle', ''),
                           c.get('is_engine_hint', False), c.get('is_combo_piece', False),
                           overrides)
        item = dict(c)
        item['role'] = role
        grouped[role].append(item)
    return grouped
