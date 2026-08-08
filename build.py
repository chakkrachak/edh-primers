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

def copy_btn(card_names, label="📋"):
    data = H.escape(", ".join(card_names))
    return (f'<button class="copy-btn" data-copy="{data}" '
            f'onclick="copyText(this.getAttribute(\'data-copy\'))" '
            f'title="Copy card list">{label}</button>')

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
        'extra_table_rows': d.get('extra_table_rows', ''),
        'rarity': d['rarity'],
        'legality': d['legality'],
        'oracle_text': d['oracle_text'],
        'quick_read': d['quick_read'],
        'plan_html': d['plan_html'],
        'source_html': d['source_html'],
        'plan_bigs': ''.join(big_card(d['imgs'].get(n, ''), n, 185) for n in d['plan_cards']),
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
            'explanation': info['explanation'],
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
        produces = [f.get('name', '') for f in c.get('produces', []) if isinstance(f, dict)][:6]
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
            'produces': produces,
            'prereq_bullets': prereq_bullets,
            'exec_steps': exec_steps,
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

def build_precon(slug):
    """Rend une évaluation de deck (precon) : data/precons/<slug>.json + templates/precon.html."""
    with open(f'{PRECON_DIR}/{slug}.json', encoding='utf-8') as f:
        d = json.load(f)

    def bold(text):
        """Convertit **bold** markdown en <strong> (pour les bullets pédagogiques)."""
        if not isinstance(text, str):
            return text
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    def bold_list(items):
        return [bold(x) for x in (items or [])]

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
        'commander_name': cmdr['name'],
        'mana_cost_html': mana_symbols(cmdr.get('mana_cost', '')),
        'type_line': cmdr.get('type_line', ''),
        'color_id': '🌈 Esper (W/U/B)',
        'power': cmdr.get('power', ''),
        'toughness': cmdr.get('toughness', ''),
        'oracle_text': mana_symbols(cmdr.get('oracle', '')),
        'commander_big': big_card(cmdr.get('img', ''), cmdr['name'], 260),
    }

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
                'explanation': c.get('explanation', ''),
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
            produces = [f.get('name', '') for f in c.get('produces', []) if isinstance(f, dict)][:6]
            desc = c.get('description') or ''
            prereq = c.get('notablePrerequisites') or c.get('easyPrerequisites') or ''
            prereq_bullets = [s.strip() for s in re.split(r'[.;]\s*|\n', prereq) if s.strip()]
            exec_steps = [s.strip() for s in re.split(r'\.\s*|\n', desc) if s.strip()]
            plan_combos.append({
                'title': c.get('title', ' + '.join(names)),
                'copy_btn': copy_btn(names),
                'bigs': ''.join(big_card(imgs_global.get(n, ''), n, 110) for n in names),
                'identity': c.get('identity', ''),
                'produces': produces,
                'prereq_bullets': prereq_bullets,
                'exec_steps': exec_steps,
                'popularity': c.get('popularity', 0),
                'in_deck': c.get('in_deck', []),
            })
        plans.append({
            'tag': p['tag'], 'decks': p['decks'], 'tag_cls': tag_cls, 'tag_slug': tag_slug,
            'description': bold_list(p.get('description', '') if isinstance(p.get('description'), list) else [p.get('description', '')]),
            'win': bold_list(p.get('win', '') if isinstance(p.get('win'), list) else [p.get('win', '')]),
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
        'text': bold_list(vtext if isinstance(vtext, list) else [vtext]),
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

def build_index():
    """Régénère index.html : data/index.json + extraction depuis les rapports générés."""
    with open(f'{BASE}/data/index.json', encoding='utf-8') as f:
        idx = json.load(f)
    template = open(f'{BASE}/templates/index.html', encoding='utf-8').read()

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
        # pips from color identity
        m = re.search(r'<strong>Color identity</strong></td><td>([^<]+)</td>', html)
        ci = m.group(1) if m else ''
        pip_map = {'W': ('pip-w', 'White'), 'U': ('pip-u', 'Blue'), 'B': ('pip-b', 'Black'),
                   'R': ('pip-r', 'Red'), 'G': ('pip-g', 'Green')}
        pips = [{'cls': cls, 'title': title} for letter, (cls, title) in pip_map.items() if letter in ci]
        # high synergy thumbs — the FIRST role section (the plan core per the display order,
        # Engines when present, otherwise the first role that exists, e.g. Wincons for Slogurk).
        # NOTE: "Engines" also appears in the game-plan text; anchor on the role-section h3 + take
        # until the NEXT role section (not the first card-grid after any mention).
        m = re.search(r'<h2 id="s3">.*?</h2>.*?<div class="category"><h3>(?:<[^>]*>|[^<])*?(?:Engines|Wincons|Flex|Card Advantage|Ramp|Wipes|Interaction|Lands).*?</h3>(.*?)(?:<div class="category">|<h2 )', html, re.S)
        thumbs = []
        if m:
            imgs = re.findall(r'<img src="(https://cards\.scryfall\.io/[^"]+)"[^>]*data-name="([^"]*)"', m.group(1))
            for u, nm in imgs[:6]:
                thumbs.append({'name': nm, 'img': u})
        cards.append({
            'href': path.replace(f'{OUT_DIR}/', 'content/'),
            'name': name,
            'img': img,
            'pips': pips,
            'plan': idx['plans'].get(name, ''),
            'desc': idx['descriptions'].get(name, ''),
            'thumbs': thumbs,
        })
        print(f"✓ index: {name} (pips={len(pips)}, thumbs={len(thumbs)})")

    ctx = dict(idx)
    ctx['cards'] = cards
    html_out = render(template, ctx)
    with open(f'{BASE}/index.html', 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f"✓ index.html régénéré ({len(cards)} cards)")

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
