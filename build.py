#!/usr/bin/env python3
"""build.py — assembleur unique : data/decks/*.json + templates/ → content/.
Usage : python3 build.py [slug1 slug2 …]   (sans args : tous les decks)
"""
import json, os, re, html as H, sys, datetime, glob

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, 'build'))
from render import render, mana_symbols

DATA_DIR = f'{BASE}/data/decks'
TEMPLATE = f'{BASE}/templates/report.html'
OUT_DIR = f'{BASE}/content'

def produces_of(combo):
    """Noms des Produces d'un combo — gère les 2 formats Spellbook :
    legacy [{'name': ...}] et récent [{'feature': {'name': ...}, 'quantity': ...}]."""
    out = []
    for f in combo.get('produces', []) or []:
        if isinstance(f, dict):
            name = f.get('name') or (f.get('feature') or {}).get('name', '')
            if name:
                out.append(name)
    return out[:6]

def copy_btn(card_names, label="📋"):
    data = H.escape(", ".join(card_names))
    return (f'<button class="copy-btn" data-copy="{data}" '
            f'onclick="copyText(this.getAttribute(\'data-copy\'))" '
            f'title="Copy card list">{label}</button>')

def cardify(text, card_names, img_of=None):
    """Transforme chaque nom de carte présent dans le texte en badge cliquable (zoom modal).

    - Matche les noms les PLUS LONGS d'abord (évite « Cloud » dans « Cloud, Midgar Mercenary »).
    - Ajoute la forme COURTE (avant la virgule) de chaque nom pour matcher les mentions
      au prénom (ex. « Adeline » pour « Adeline, Resplendent Cathar ») — sauf si elle est
      un mot anglais générique (Captain, Sword…) ou trop courte (< 4 lettres).
    - Ignore les balises HTML existantes (<strong>, <em>, <img>…) et leurs attributs.
    - Tolère les apostrophes ' et ’ (ex. Sensei's Divining Top vs Sensei’s).
    - img_of(name) → URL d'image optionnelle (badge cliquable si fournie, sinon badge texte).
    """
    if not text or not card_names:
        return text
    # mots anglais génériques — jamais comme forme courte (faux positifs)
    BAD_SHORT = {'captain', 'herald', 'general', 'champion', 'master', 'lord', 'lady',
                 'king', 'queen', 'angel', 'demon', 'dragon', 'spirit', 'beast', 'giant',
                 'wizard', 'warrior', 'soldier', 'knight', 'path', 'sword', 'shield',
                 'helm', 'crown', 'throne', 'palace', 'fort', 'castle', 'tower', 'gate',
                 'hope', 'faith', 'light', 'dawn', 'night', 'moon', 'sun', 'star',
                 'storm', 'wind', 'fire', 'flame', 'ice', 'frost', 'time', 'world',
                 'life', 'death', 'war', 'peace', 'power', 'glory', 'honor', 'justice',
                 'mercy', 'saint', 'prophet', 'priest', 'monk', 'sky', 'sea', 'earth'}
    # noms complets + formes courtes (avant virgule), triés par longueur décroissante.
    # short→full permet de retrouver l'image d'un badge au prénom (Adeline → Adeline, Resplendent Cathar).
    variants = set()
    short_to_full = {}
    for n in card_names:
        if not n:
            continue
        variants.add(n)
        short = n.split(',')[0].strip()
        if len(short) >= 4 and short.lower() not in BAD_SHORT:
            variants.add(short)
            short_to_full.setdefault(short, n)
    names = sorted(variants, key=len, reverse=True)
    # img_of élargi : nom exact, puis forme courte → nom complet (Adeline → Adeline, Resplendent Cathar)
    def img_lookup(name):
        if img_of:
            return img_of(name) or img_of(short_to_full.get(name, ''))
        return ''
    # patterns : apostrophes normalisées
    def esc(n):
        return re.escape(n).replace("\\'", "['’]")
    alt = '|'.join(esc(n) for n in names)
    pattern = re.compile(r'(?<![\w])(' + alt + r')(?![\w])')

    # découpe en segments HTML vs texte
    def repl_in_text(seg):
        def repl(m):
            name = m.group(1)
            img = img_lookup(name)
            if img:
                large = img.replace('/normal/', '/large/')
                return (f'<span class="card-badge" data-large="{large}" '
                        f'data-name="{H.escape(name)}" onclick="openModal(this)">'
                        f'{H.escape(name)}</span>')
            return f'<span class="card-badge">{H.escape(name)}</span>'
        return pattern.sub(repl, seg)

    parts = re.split(r'(<[^>]*>)', text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(part)          # balise HTML : inchangée
        else:
            out.append(repl_in_text(part))
    return ''.join(out)

def big_card(url, name, size=190):
    assert url.startswith("https://cards.scryfall.io/"), f"URL manquante pour {name}"
    return (f'<div class="big-card" style="width:{size}px;">'
            f'<img src="{url}" data-large="{url.replace("/normal/", "/large/")}" data-name="{H.escape(name)}" loading="lazy" '
            f'onclick="openModal(this)"/>'
            f'<div class="big-label">{H.escape(name)}</div></div>')

def syn_cls(score):
    if score is None:
        return ""
    return "syn-hi" if score >= 0.7 else ("syn-mid" if score >= 0.4 else "syn-lo")

def build_one(slug):
    with open(f'{DATA_DIR}/{slug}.json', encoding='utf-8') as f:
        d = json.load(f)

    # --- normalize synergy keys (HTML entities) ---
    synergy = {H.unescape(str(k)): v for k, v in (d['synergy'] or {}).items()}

    def syn_of(name):
        s = synergy.get(name)
        if not s or s.get('synergy') is None:
            return None
        return s['synergy']

    def oracle_of(name):
        """Oracle text d'une carte — gère les 2 formats : str direct ou dict {oracle_text, ...}."""
        o = d.get('oracle', {}).get(name, '')
        if isinstance(o, dict):
            return o.get('oracle_text', '')
        return o or ''

    # --- commander sheet ---
    commander_img = d['imgs'].get(d['commander_name'], '')
    ctx = {
        'commander_name': d['commander_name'],
        'plan_title': d['plan_title'],
        'n_combos': len(d['combos']),
        'copy_btn_cmd': copy_btn([d['commander_name']]),
        'copy_btn_plan': copy_btn(d['plan_cards']),
        'commander_big': big_card(commander_img, d['commander_name'], 260),
        'mana_cost_html': d['mana_cost_html'],
        'type_line': d['type_line'],
        'color_id': d['color_id'],
        'power': d.get('power', ''),
        'toughness': d.get('toughness', ''),
        # enlever P/T de extra_table_rows (maintenant un champ dédié) — garder Loyalty etc.
        'extra_table_rows': re.sub(r'<tr><td><strong>Power / Toughness</strong></td><td>[^<]*</td></tr>', '', d.get('extra_table_rows', '')),
        'rarity': d['rarity'],
        'legality': d['legality'],
        'oracle_text': d['oracle_text'],
        'quick_read': bold_list(d['quick_read'] if isinstance(d['quick_read'], list) else [d['quick_read']]),
        'plan_html': d['plan_html'],
        'source_html': d['source_html'],
        'combos_note': d['combos_note'],
        'gen_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # --- categories (regroupées par RÔLE — reference: role-grouping.md) ---
    # Aplatir les explications par carte (HighSynergy prime en cas de doublon)
    flat = {}
    hs_pool = set()
    if 'HighSynergy' in d.get('explanations', {}):
        hs_pool = {n for n, _ in d['explanations']['HighSynergy']}
    for key in d['cat_order']:
        for name, expl in d['explanations'][key]:
            if name not in flat:
                flat[name] = {'name': name, 'explanation': expl, 'source_cat': key}
            # HighSynergy explication prime
            if key == 'HighSynergy':
                flat[name]['explanation'] = expl
                flat[name]['source_cat'] = key
    # Combo pieces
    combo_pieces = set()
    for c in d.get('combos', []):
        for u in c.get('uses', []):
            combo_pieces.add(u['card']['name'])
    # Tous les noms de cartes connus (deck + commander + pièces de combos) pour les badges
    all_names = set(flat.keys()) | {d['commander_name']} | combo_pieces
    img_of = d['imgs'].get
    # --- cardify des textes (noms de cartes → badges cliquables) ---
    ctx['quick_read'] = [cardify(b, all_names, img_of) for b in ctx['quick_read']]
    ctx['plan_html'] = cardify(ctx['plan_html'], all_names, img_of)
    ctx['source_html'] = cardify(ctx['source_html'], all_names, img_of)
    ctx['combos_note'] = cardify(ctx['combos_note'], all_names, img_of)
    # Assignation par rôle
    from roles import assign_role, ROLE_ORDER, ROLE_TITLES, ROLE_SYNOPSES, ROLE_TARGETS
    cards_by_role = {r: [] for r in ROLE_ORDER}
    for name, info in flat.items():
        meta = d.get('card_meta', {}).get(name, {})
        oracle_txt = oracle_of(name)
        role = assign_role(name, meta, oracle_txt,
                           is_engine_hint=name in hs_pool,
                           is_combo_piece=name in combo_pieces)
        img = d['imgs'].get(name, '')
        score = syn_of(name)
        cards_by_role[role].append({
            'name': name,
            'img': img,
            'img_large': img.replace('/normal/', '/large/'),
            'explanation': cardify(info['explanation'], all_names, img_of),
            'synergy': f'{score:.2f}' if score is not None else None,
            'syn_cls': syn_cls(score) if score is not None else '',
        })
    # Ordre d'affichage : Engines → Wincons → Flex → CardAdvantage → Ramp → Wipes → Interaction → Lands
    categories = []
    for role in ROLE_ORDER:
        cards = cards_by_role[role]
        if not cards:
            continue
        cat_names = [c['name'] for c in cards]
        categories.append({
            'title': ROLE_TITLES[role],
            'synopsis': ROLE_SYNOPSES[role],
            'target': ROLE_TARGETS[role],
            'copy_btn': copy_btn(cat_names),
            'cards': cards,
            'n': len(cards),
        })
    ctx['categories'] = categories
    ctx['n_categories'] = len(categories)

    # --- combos ---
    combos = []
    for c in d['combos']:
        names = [u['card']['name'] for u in c.get('uses', [])]
        pop = c.get('popularity') or 0
        identity = c.get('identity') or ''
        produces = produces_of(c)
        desc = c.get('description') or ''
        prereq = c.get('notablePrerequisites') or c.get('easyPrerequisites') or ''
        prereq_bullets = [s.strip() for s in re.split(r'[.;]\s*|\n', prereq) if s.strip()]
        exec_steps = [s.strip() for s in re.split(r'\.\s*|\n', desc) if s.strip()]
        combos.append({
            'title': " + ".join(names),
            'copy_btn': copy_btn(names),
            'identity': identity,
            'popularity': pop,
            'bigs': ''.join(big_card(d['imgs'].get(n, ''), n, 150) for n in names),
            'produces': [cardify(p, all_names, img_of) for p in produces],
            'prereq_bullets': [cardify(b, all_names, img_of) for b in prereq_bullets],
            'exec_steps': [cardify(s, all_names, img_of) for s in exec_steps],
        })
    ctx['combos'] = combos

    # --- render ---
    template = open(TEMPLATE, encoding='utf-8').read()
    html_out = render(template, ctx)

    now = datetime.datetime.now()
    filename = f"EDH-Primer-{d['deck_slug']}-{now.strftime('%Y%m%d-%H%M')}.html"
    path = f'{OUT_DIR}/{filename}'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    n_cards = sum(len(v) for v in d['explanations'].values())
    print(f"✓ {d['commander_name']}: {n_cards} cartes, {len(combos)} combos → {filename}")
    return path

# ------------------------------------------------------------
# Precon / deck-list evaluation (mtg-precon-evaluation skill)
# ------------------------------------------------------------
PRECON_TEMPLATE = f'{BASE}/templates/precon.html'
PRECON_DIR = f'{BASE}/data/precons'

PRECON_TITLES = {
    'Creatures': '🧝 Creatures', 'Instants': '⚡ Instants', 'Sorceries': '📜 Sorceries',
    'Artifacts': '⚔️ Artifacts', 'Enchantments': '🌿 Enchantments',
    'UtilityLands': '🏰 Utility Lands', 'ManaBase': '🌲 Lands / Mana Base',
}
PRECON_SYNOPSES = {
    'Creatures': 'Creatures of the list', 'Instants': 'Instants of the list',
    'Sorceries': 'Sorceries of the list', 'Artifacts': 'Artifacts of the list',
    'Enchantments': 'Enchantments of the list',
    'UtilityLands': 'Utility lands', 'ManaBase': 'Mana base (lands + rocks)',
}

def bold(text):
    """Convertit **bold** markdown en <strong> (pour les bullets pédagogiques)."""
    if not isinstance(text, str):
        return text
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

def bold_list(items):
    return [bold(x) for x in (items or [])]

def verdict_quick_read(d):
    """Résumé du plan favorisé en bullets pédagogiques — MÊME FORMAT que le quick read des
    primers (description du plan + win conditions, lead-ins en gras)."""
    plans = d.get('plans', [])
    if not plans:
        return []
    # plan dominant = le plus de decks (le favori du verdict)
    top = max(plans, key=lambda p: p.get('decks', 0))
    out = []
    for b in (top.get('description') or [])[:3]:
        out.append(b)
    wins = top.get('win') or []
    if wins:
        out.append(wins[0])
    return out

def build_precon(slug):
    """Rend une évaluation de deck (precon) : data/precons/<slug>.json + templates/precon.html."""
    with open(f'{PRECON_DIR}/{slug}.json', encoding='utf-8') as f:
        d = json.load(f)

    cmdr = d['commander']
    # images globales : cartes du deck + cartes de combos (pour les blocs combo)
    imgs_global = {}
    for cat in d['cards'].values():
        for c in cat:
            imgs_global[c['name']] = c.get('img', '')
    for p in d['plans']:
        for c in p.get('combos', []):
            for u in c.get('uses', []):
                imgs_global.setdefault(u['card']['name'], u.get('card', {}).get('imageUriFrontNormal', ''))
    ctx = {
        'precon_name': d['precon_name'],
        'precon_set': cmdr.get('set_name', cmdr.get('set', '')),
        'commander_name': cmdr['name'],
        'mana_cost_html': mana_symbols(cmdr.get('mana_cost', '')),
        'type_line': cmdr.get('type_line', ''),
        'color_id': '🌈 Esper (W/U/B)',
        'power': cmdr.get('power', ''),
        'toughness': cmdr.get('toughness', ''),
        'rarity': cmdr.get('rarity', ''),
        'legality': cmdr.get('legality', 'legal'),
        'oracle_text': mana_symbols(cmdr.get('oracle', '')),
        'commander_big': big_card(cmdr.get('img', ''), cmdr['name'], 260),
        'copy_btn_cmd': copy_btn([cmdr['name']]),
        # quick read = résumé du verdict (bullets pédagogiques)
        'quick_read': bold_list(verdict_quick_read(d)),
    }

    # Tous les noms de cartes connus (deck + commander + pièces de combos) pour les badges
    all_names = set()
    for cat in d['cards'].values():
        for c in cat:
            all_names.add(c['name'])
    all_names.add(cmdr['name'])
    for p in d['plans']:
        for cb in p.get('combos', []):
            for u in cb.get('uses', []):
                all_names.add(u['card']['name'])
    img_of = imgs_global.get
    # cardify des textes
    ctx['quick_read'] = [cardify(b, all_names, img_of) for b in ctx['quick_read']]

    # --- categories (regroupées par RÔLE — même moteur que les rapports) ---
    from roles import assign_role, ROLE_ORDER, ROLE_TITLES, ROLE_SYNOPSES, ROLE_TARGETS
    # combo pieces (toutes les cartes des combos de tous les plans)
    combo_pieces = set()
    for p in d['plans']:
        for cb in p.get('combos', []):
            for u in cb.get('uses', []):
                combo_pieces.add(u['card']['name'])
    # hint engine : cartes du deck dans le pool High Synergy du commander
    hs_names = set()
    for cat in d['cards'].values():
        for c in cat:
            if c.get('in_main_hs'):
                hs_names.add(c['name'])
    cards_by_role = {r: [] for r in ROLE_ORDER}
    n_total = 0
    for cat in d['cards'].values():
        for c in cat:
            meta = d.get('card_meta', {}).get(c['name'], {})
            oracle_txt = d.get('oracle', {}).get(c['name'], '')
            role = assign_role(c['name'], meta, oracle_txt,
                               is_engine_hint=c['name'] in hs_names,
                               is_combo_piece=c['name'] in combo_pieces)
            score = c.get('synergy')
            cards_by_role[role].append({
                'name': c['name'], 'img': c['img'],
                'explanation': cardify(c.get('explanation', ''), all_names, img_of),
                'synergy': f'{score:.2f}' if score is not None else None,
                'syn_cls': syn_cls(score),
            })
            n_total += 1
    categories = []
    for role in ROLE_ORDER:
        cards = cards_by_role[role]
        if not cards:
            continue
        names = [c['name'] for c in cards]
        categories.append({
            'title': ROLE_TITLES[role], 'synopsis': ROLE_SYNOPSES[role],
            'target': ROLE_TARGETS[role],
            'copy_btn': copy_btn(names), 'cards': cards,
            'n': len(cards),
        })
    ctx['categories'] = categories
    ctx['n_cards'] = sum(c['n'] for c in categories)
    ctx['n_total'] = n_total
    ctx['n_categories'] = len(categories)

    # --- plans ---
    plans = []
    for p in d['plans']:
        match_cards = []
        for mname in p.get('deck_matches', []):
            # find card info in cards dicts
            card_info = None
            for cat in d['cards'].values():
                for c in cat:
                    if c['name'] == mname:
                        card_info = c
                        break
                if card_info:
                    break
            score = (card_info or {}).get('synergy')
            expl = (card_info or {}).get('explanation', '')
            match_cards.append({
                'name': mname,
                'img': (card_info or {}).get('img', ''),
                'synergy': f'{score:.2f}' if score is not None else None,
                'syn_cls': syn_cls(score),
                'explanation': expl,
            })
        hs_len = max(len(p.get('high_synergy', [])), 1)
        pct = int(round(len(p.get('deck_matches', [])) / hs_len * 100))
        tag_decks = p['decks']
        tag_cls = 'hi' if tag_decks > 500 else ('mid' if tag_decks > 100 else 'lo')
        tag_slug = re.sub(r'[^a-z0-9]+', '-', p['tag'].lower()).strip('-')
        # combos for this plan (same presentation as primers: Produces/Prerequisites/Execution bullets)
        plan_combos = []
        for c in p.get('combos', []):
            names = [u['card']['name'] for u in c.get('uses', [])]
            produces = produces_of(c)
            desc = c.get('description') or ''
            prereq = c.get('notablePrerequisites') or c.get('easyPrerequisites') or ''
            prereq_bullets = [s.strip() for s in re.split(r'[.;]\s*|\n', prereq) if s.strip()]
            exec_steps = [s.strip() for s in re.split(r'\.\s*|\n', desc) if s.strip()]
            plan_combos.append({
                'title': c.get('title', ' + '.join(names)),
                'copy_btn': copy_btn(names),
                'bigs': ''.join(big_card(imgs_global.get(n, ''), n, 110) for n in names),
                'identity': c.get('identity', ''),
                'produces': [cardify(p, all_names, img_of) for p in produces],
                'prereq_bullets': [cardify(b, all_names, img_of) for b in prereq_bullets],
                'exec_steps': [cardify(s, all_names, img_of) for s in exec_steps],
                'popularity': c.get('popularity', 0),
                'in_deck': c.get('in_deck', []),
            })
        plans.append({
            'tag': p['tag'], 'decks': p['decks'], 'tag_cls': tag_cls, 'tag_slug': tag_slug,
            'description': [cardify(b, all_names, img_of) for b in bold_list(p.get('description', '') if isinstance(p.get('description'), list) else [p.get('description', '')])],
            'win': [cardify(b, all_names, img_of) for b in bold_list(p.get('win', '') if isinstance(p.get('win'), list) else [p.get('win', '')])],
            'high_synergy': p.get('high_synergy', []),
            'deck_matches': p.get('deck_matches', []),
            'match_cards': match_cards,
            'combos': plan_combos,
            'pct': pct,
        })
    ctx['plans'] = plans
    ctx['top_n'] = 6

    # --- verdict ---
    verdict = d['verdict']
    vtext = verdict.get('text', '')
    ctx['verdict'] = {
        'favored': verdict.get('favored', ''),
        'text': [cardify(b, all_names, img_of) for b in bold_list(vtext if isinstance(vtext, list) else [vtext])],
    }

    # --- structure analysis (build principles) ---
    structure = d.get('structure', {})
    roles = []
    for r in structure.get('roles', []):
        lo, hi = r['ideal'].split('-')
        lo, hi = int(lo), int(hi)
        span = max(hi - lo, 1)
        roles.append({
            'role': r['role'], 'slots': r['slots'], 'ideal': r['ideal'], 'status': r['status'],
            'pct': max(0, min(100, int(round(r['slots'] / (hi * 1.4) * 100)))),
            'fill_cls': 'fill-under' if r['status'] == 'under' else ('fill-over' if r['status'] == 'over' else ''),
        })
    ctx['structure'] = {
        'roles': roles,
        'avg_cmc': f"{structure.get('avg_cmc_nonland', 0):.2f}",
        'avg_cmc_num': structure.get('avg_cmc_nonland', 0),
        'summary': bold_list(structure.get('summary', []) if isinstance(structure.get('summary'), list) else [structure.get('summary', '')]),
    }

    template = open(PRECON_TEMPLATE, encoding='utf-8').read()
    html_out = render(template, ctx)

    now = datetime.datetime.now()
    filename = f"EDH-Eval-{slug}-{now.strftime('%Y%m%d-%H%M')}.html"
    path = f'{OUT_DIR}/{filename}'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f"✓ Eval {d['precon_name']}: {ctx['n_cards']} cartes, {len(plans)} plans → {filename}")
    return path

def _color_letters(ci_text):
    """Extrait les lettres W/U/B/R/G depuis un texte d'identité (ex. '🔵⚫ Dimir (U/B)' → 'UB')."""
    return ''.join(c for c in 'WUBRG' if c in (ci_text or ''))

def build_index():
    """Régénère index.html : data/index.json + extraction depuis les rapports générés."""
    with open(f'{BASE}/data/index.json', encoding='utf-8') as f:
        idx = json.load(f)
    template = open(f'{BASE}/templates/index.html', encoding='utf-8').read()

    pip_map = {'W': ('pip-w', 'White'), 'U': ('pip-u', 'Blue'), 'B': ('pip-b', 'Black'),
               'R': ('pip-r', 'Red'), 'G': ('pip-g', 'Green')}

    def pips_for(letters):
        return [{'cls': cls, 'title': title} for letter, (cls, title) in pip_map.items() if letter in letters]

    # --- primers ---
    cards = []
    # Le mapping nom→slug vient des JSON eux-mêmes (deck_slug + commander_name) —
    # plus de DECK_SLUGS à maintenir dans le code.
    slug_by_name = {}
    for dpath in sorted(glob.glob(f'{DATA_DIR}/*.json')):
        with open(dpath, encoding='utf-8') as f:
            d = json.load(f)
        slug_by_name[d.get('commander_name', '')] = d.get('deck_slug', '')
    for name in idx['decks_order']:
        slug = slug_by_name.get(name)
        if not slug:
            print(f"⚠️ index: pas de deck JSON pour {name}")
            continue
        # newest report for this slug
        files = sorted(glob.glob(f'{OUT_DIR}/EDH-Primer-{slug}-*.html'))
        if not files:
            print(f"⚠️ index: pas de rapport pour {name}")
            continue
        path = files[-1]
        html = open(path, encoding='utf-8').read()
        # commander art
        m = re.search(r'<div class="big-card" style="width:260px;"><img src="([^"]+)"', html)
        img = m.group(1) if m else ''
        if not img:
            m = re.search(r'<img src="(https://cards\.scryfall\.io/[^"]+)"[^>]*data-name="[^"]*"[^>]*/>', html)
            img = m.group(1) if m else ''
        # pips + colors from color identity
        m = re.search(r'<strong>Color identity</strong></td><td>([^<]+)</td>', html)
        ci = m.group(1) if m else ''
        letters = _color_letters(ci)
        # high synergy thumbs — the commander's EDHREC High Synergy pool, sorted by synergy
        # score descending (most synergistic first). Read from the deck JSON, not the HTML.
        thumbs = []
        dpath = f'{DATA_DIR}/{slug}.json'
        if os.path.exists(dpath):
            with open(dpath, encoding='utf-8') as f:
                deck = json.load(f)
            hs_pool = dict(deck.get('explanations', {}).get('HighSynergy', []))
            syn = deck.get('synergy', {})
            scored = []
            for nm in hs_pool:
                s = syn.get(nm, {})
                score = s.get('synergy') if isinstance(s, dict) else s
                scored.append((nm, score if isinstance(score, (int, float)) else -1))
            scored.sort(key=lambda x: x[1], reverse=True)
            for nm, _ in scored[:6]:
                thumbs.append({'name': nm, 'img': deck.get('imgs', {}).get(nm, '')})
        cards.append({
            'href': path.replace(f'{OUT_DIR}/', 'content/'),
            'name': name,
            'img': img,
            'pips': pips_for(letters),
            'colors': letters,
            'kind': 'primer',
            'plan': idx['plans'].get(name, ''),
            'desc': idx['descriptions'].get(name, ''),
            'thumbs': thumbs,
        })
        print(f"✓ index: {name} (pips={len(pips_for(letters))}, thumbs={len(thumbs)})")

    # --- evaluations (precons) ---
    evals = []
    eval_slug_by_name = {}
    for dpath in sorted(glob.glob(f'{PRECON_DIR}/*.json')):
        with open(dpath, encoding='utf-8') as f:
            d = json.load(f)
        eval_slug_by_name[d.get('commander', {}).get('name', '')] = d.get('precon_slug', '')
    for name in idx.get('evals_order', []):
        slug = eval_slug_by_name.get(name)
        if not slug:
            print(f"⚠️ index: pas de JSON éval pour {name}")
            continue
        files = sorted(glob.glob(f'{OUT_DIR}/EDH-Eval-{slug}-*.html'))
        if not files:
            print(f"⚠️ index: pas d'éval pour {name}")
            continue
        path = files[-1]
        with open(f'{PRECON_DIR}/{slug}.json', encoding='utf-8') as f:
            deck = json.load(f)
        cmdr = deck.get('commander', {})
        img = cmdr.get('img', '')
        # colors from mana cost letters
        mc = cmdr.get('mana_cost', '')
        letters = ''.join(c for c in 'WUBRG' if c in mc)
        # thumbs: cards in the commander's HS pool (in_main_hs), sorted by synergy
        hs = []
        for cat in deck.get('cards', {}).values():
            for c in cat:
                if c.get('in_main_hs'):
                    hs.append((c['name'], c.get('synergy') or -1))
        hs.sort(key=lambda x: x[1], reverse=True)
        thumbs = [{'name': nm, 'img': next((c.get('img', '') for cat in deck.get('cards', {}).values()
                                            for c in cat if c['name'] == nm), '')} for nm, _ in hs[:6]]
        evals.append({
            'href': path.replace(f'{OUT_DIR}/', 'content/'),
            'name': name,
            'img': img,
            'pips': pips_for(letters),
            'colors': letters,
            'kind': 'eval',
            'plan': idx.get('eval_plans', {}).get(name, ''),
            'desc': idx.get('eval_descriptions', {}).get(name, ''),
            'thumbs': thumbs,
        })
        print(f"✓ index eval: {name} (pips={len(pips_for(letters))}, thumbs={len(thumbs)})")

    ctx = dict(idx)
    ctx['cards'] = cards
    ctx['evals'] = evals
    ctx['n_primers'] = len(cards)
    ctx['n_evals'] = len(evals)
    ctx['n_total'] = len(cards) + len(evals)
    html_out = render(template, ctx)
    with open(f'{BASE}/index.html', 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f"✓ index.html régénéré ({len(cards)} primers + {len(evals)} evals)")
    check_links()

def check_links():
    """Garde-fou : après régénération de l'index, vérifie que TOUS les liens internes
    (content/…) résolvent vers un fichier existant. Un lien cassé = ancienne version
    restée dans l'index après purge de content/ — doit être détecté AVANT le push."""
    html = open(f'{BASE}/index.html', encoding='utf-8').read()
    links = sorted(set(re.findall(r'href="(content/[^"]+)"', html)))
    broken = [l for l in links if not os.path.exists(f'{BASE}/{l}')]
    if broken:
        print(f"❌ CHECK LINKS: {len(broken)} lien(s) cassé(s) dans index.html →")
        for l in broken:
            print(f"   ⚠️ {l}")
        print("   → Régénérer les rapports concernés ou purger content/ puis relancer build.py")
        return False
    print(f"✓ CHECK LINKS: {len(links)} liens internes, 0 cassé")
    return True

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    args = sys.argv[1:]
    if args and args[0] == '--index':
        build_index()
        return
    if args and args[0] == '--precon':
        for slug in args[1:]:
            build_precon(slug)
        return
    slugs = args or [f[:-5] for f in sorted(os.listdir(DATA_DIR)) if f.endswith('.json')]
    for slug in slugs:
        try:
            build_one(slug)
        except Exception as e:
            print(f"⚠️ {slug}: {e}")
    build_index()

if __name__ == '__main__':
    main()
