#!/usr/bin/env python3
"""Full-document completeness audit for the edh-primers static site.

Run from the repo root:  python3 scripts/audit_documents.py   (or copy next to build.py)

Checks, per content/*.html file:
  1. size >= 30k chars
  2. no empty <img src="">
  3. no literal ** markdown
  4. no French residuals (the known leak terms)
  5. commander big-card present
  6. at least 5 cardify badges
  7. every src= URL matches cards.scryfall.io | svgs.scryfall.io | data:
  8. TOC anchor hrefs (#sN) all have a matching <h2 id="sN">
Plus cross-document checks:
  9. every content/ link in index.html resolves to an existing file
 10. random HTTP sample of card image URLs returns 200/304
 11. L2 fiche multi-plan card coverage (reports cards in >=2 plans missing per-plan texts;
     NOTE: legacy fiches are known-incomplete but those cards never appear in documents,
     so this is informational, not a failure)

Exit code 0 = all green; 1 = problems found.
"""
import glob, os, random, re, subprocess, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, 'content')
FR_TERMS = r'\b(finisseurs|pioche|accélération|Prérequis|Exécution|Copier la liste|Carte en plein écran)\b'
SRC_OK = r'src="(?!https://cards\.scryfall\.io|https://svgs\.scryfall\.io|data:)[^"]+"'

def check_file(path):
    h = open(path, encoding='utf-8').read()
    problems = []
    if len(h) < 30000:
        problems.append(f'taille anormale ({len(h)} chars)')
    if '<img src="">' in h:
        problems.append(f'{h.count(chr(60)+"img src="+chr(34)+chr(34)+chr(62))} img vides')
    if re.findall(r'\*\*', h):
        problems.append('** littéraux')
    fr = re.findall(FR_TERMS, h, re.I)
    if fr:
        problems.append(f'FR résiduel: {fr[:3]}')
    if 'big-card' not in h:
        problems.append('pas de big-card commander')
    nb = h.count('class="card-badge"')
    if nb < 5:
        problems.append(f'peu de card-badges ({nb})')
    non_scry = re.findall(SRC_OK, h)
    if non_scry:
        problems.append(f'{len(non_scry)} URLs non-scryfall: {non_scry[:2]}')
    # TOC anchors
    toc = re.findall(r'<li><a href="#(s\d+)"', h)
    secs = set(re.findall(r'<h2 id="(s\d+)"', h))
    missing = [a for a in toc if a not in secs]
    if missing:
        problems.append(f'TOC→sections manquantes: {missing}')
    return problems

def main():
    files = sorted(glob.glob(os.path.join(CONTENT, '*.html')))
    issues = []
    for f in files:
        probs = check_file(f)
        name = os.path.basename(f)
        if probs:
            issues.append((name, probs))
            print(f"PROBLÈME {name[:58]}")
            for p in probs:
                print(f"         └ {p}")
        else:
            print(f"OK        {name[:58]}")
    print(f"\n=== {len(files) - len(issues)}/{len(files)} documents OK ===")

    # index links
    idx = os.path.join(ROOT, 'index.html')
    if os.path.exists(idx):
        h = open(idx, encoding='utf-8').read()
        links = re.findall(r'href="(content/[^"]+)"', h)
        broken = [l for l in links if not os.path.exists(os.path.join(ROOT, l))]
        print(f"Index: {len(links)} liens, {len(broken)} cassés {broken if broken else 'OK'}")
        if broken:
            issues.append(('index', broken))

    # HTTP sample of images
    all_urls = []
    for f in files:
        h = open(f, encoding='utf-8').read()
        all_urls.extend(re.findall(r'src="(https://cards\.scryfall\.io/[^"]+)"', h))
    random.seed(42)
    sample = random.sample(all_urls, min(25, len(all_urls)))
    bad = []
    for u in sample:
        try:
            r = subprocess.run(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
                                '--max-time', '15', '-I', u], capture_output=True, text=True, timeout=20)
            if r.stdout.strip() not in ('200', '304'):
                bad.append((u[:70], r.stdout.strip()))
        except Exception as e:
            bad.append((u[:70], str(e)[:30]))
    print(f"Images HTTP sample {len(sample)}: {len(sample)-len(bad)} OK, {len(bad)} problems")
    for b in bad[:5]:
        print(f"  {b}")
    if bad:
        issues.append(('images-http', bad))

    # fiche multi-plan coverage (informational)
    sys.path.insert(0, os.path.join(ROOT, 'build'))
    for fp in sorted(glob.glob(os.path.join(ROOT, 'data/cache/l2/commanders/*.json'))):
        try:
            f = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue
        cpt = f.get('card_plan_texts', {})
        plans = f.get('plans', [])
        if not plans:
            continue
        card_plans = {}
        for p in plans:
            for hh in p.get('high_synergy', []):
                nm = hh if isinstance(hh, str) else hh.get('name', '')
                card_plans.setdefault(nm, []).append(p['tag'])
        missing = [n for n, ps in card_plans.items() if len(ps) >= 2 and n not in cpt]
        if missing:
            print(f"INFO fiche {f['commander']['name'][:32]:34} multi-plans sans texte: {missing}")
    return 1 if issues else 0

if __name__ == '__main__':
    sys.exit(main())
