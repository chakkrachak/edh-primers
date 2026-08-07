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

    # --- categories ---
    categories = []
    for key in d['cat_order']:
        title, synopsis = d['cat_synopsis'][key]
        cards = []
        for name, expl in d['explanations'][key]:
            img = d['imgs'].get(name, '')
            score = syn_of(name)
            cards.append({
                'name': name,
                'img': img,
                'img_large': img.replace('/normal/', '/large/'),
                'explanation': expl,
                'synergy': f'{score:.2f}' if score is not None else None,
                'syn_cls': syn_cls(score) if score is not None else '',
            })
        cat_names = [c['name'] for c in cards]
        categories.append({'title': title, 'synopsis': synopsis, 'copy_btn': copy_btn(cat_names), 'cards': cards})
    ctx['categories'] = categories

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

def build_index():
    """Régénère index.html : data/index.json + extraction depuis les rapports générés."""
    with open(f'{BASE}/data/index.json', encoding='utf-8') as f:
        idx = json.load(f)
    template = open(f'{BASE}/templates/index.html', encoding='utf-8').read()

    cards = []
    for name in idx['decks_order']:
        slug = DECK_SLUGS.get(name)
        if not slug:
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
        # high synergy thumbs
        m = re.search(r'<div class="category"><h3>🌟 High Synergy Cards.*?<div class="card-grid">(.*?)</div></div>', html, re.S)
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

DECK_SLUGS = {
    'Aminatou, the Fateshifter': 'aminatou-the-fateshifter',
    'Cloud, Ex-SOLDIER': 'cloud-ex-soldier',
    'Gisa and Geralf': 'gisa-and-geralf',
    'Lathril, Blade of the Elves': 'lathril-blade-of-the-elves',
    'Saheeli, Radiant Creator': 'saheeli-radiant-creator',
    'Slogurk, the Overslime': 'slogurk-the-overslime',
    'Terra, Herald of Hope': 'terra-herald-of-hope',
    "Yuriko, the Tiger's Shadow": 'yuriko-the-tigers-shadow',
}

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    args = sys.argv[1:]
    if args and args[0] == '--index':
        build_index()
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
