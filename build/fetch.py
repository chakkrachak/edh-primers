#!/usr/bin/env python3
"""build/fetch.py — Cache niveau 1 (API).

Stocke les réponses API brutes sous data/cache/l1/<source>/<key>.json, horodatées,
avec un index data/cache/l1/index.json (clé → source / fetched_at / ttl_days).

Usage :
    from fetch import scryfall_batch, scryfall_named, scryfall_fuzzy,
                     edhrec_page, edhrec_tag, spellbook_combos, moxfield_deck

Principes :
    - Immutable : une réponse écrite n'est jamais modifiée (clé = hash déterministe).
    - TTL par source : Scryfall 30 j, EDHREC 7 j, Spellbook 7 j, Moxfield 30 j.
    - Les tokens/clés API ne sont JAMAIS stockés (seules les réponses publiques).
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L1_DIR = f'{BASE}/data/cache/l1'
INDEX = f'{L1_DIR}/index.json'

TTL = {
    'scryfall': 30,
    'edhrec': 7,
    'spellbook': 7,
    'moxfield': 30,
}

# ---------------------------------------------------------------------------
# Cœur du cache
# ---------------------------------------------------------------------------

def _key(*parts):
    """Clé déterministe (SHA-1 court) depuis les parties de la requête."""
    raw = '|'.join(str(p) for p in parts)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def _index_load():
    if os.path.exists(INDEX):
        try:
            return json.load(open(INDEX, encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _index_save(idx):
    os.makedirs(L1_DIR, exist_ok=True)
    with open(INDEX, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


def _path(source, key):
    return f'{L1_DIR}/{source}/{key}.json'


def _fresh(path, ttl_days):
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    return age < ttl_days * 86400


def get(source, key, fetcher, ttl_days=None, force=False):
    """Retourne la réponse cacheée si fraîche, sinon fetch + écrit.

    fetcher() doit retourner le contenu à stocker (dict/list/str).
    Retourne (data, from_cache: bool).
    """
    ttl = ttl_days or TTL.get(source, 7)
    path = _path(source, key)
    if not force and _fresh(path, ttl):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f), True
        except Exception:
            pass  # cache corrompu → re-fetch
    data = fetcher()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    idx = _index_load()
    idx[key] = {'source': source, 'fetched_at': int(time.time()), 'ttl_days': ttl}
    _index_save(idx)
    return data, False


def status():
    """État du cache : par source, nb d'entrées + âge max."""
    idx = _index_load()
    out = {}
    now = time.time()
    for key, meta in idx.items():
        src = meta['source']
        path = _path(src, key)
        age = now - os.path.getmtime(path) if os.path.exists(path) else None
        e = out.setdefault(src, {'entries': 0, 'max_age_days': 0})
        e['entries'] += 1
        if age is not None:
            e['max_age_days'] = max(e['max_age_days'], round(age / 86400, 1))
    return out


def prune():
    """Supprime les entrées périmées (âge > TTL). Retourne le nb de fichiers supprimés."""
    idx = _index_load()
    removed = 0
    now = time.time()
    for key, meta in list(idx.items()):
        src = meta['source']
        ttl = meta.get('ttl_days', TTL.get(src, 7))
        path = _path(src, key)
        if os.path.exists(path) and (now - os.path.getmtime(path)) > ttl * 86400:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
            del idx[key]
    _index_save(idx)
    return removed


# ---------------------------------------------------------------------------
# Helper HTTP (curl — le repo n'a pas requests)
# ---------------------------------------------------------------------------

def _curl(url, timeout=40, data=None, retries=3, json_ok=True):
    """curl avec retry + backoff — les API (surtout Scryfall derrière Cloudflare)
    renvoient parfois des pages « Application Error » transitoires (HTML, pas JSON).
    json_ok=True : la réponse doit commencer par { ou [ (retry sinon)."""
    delay = 2.0
    last_err = None
    for attempt in range(retries):
        cmd = ['curl', '-s', '--max-time', str(timeout)]
        if data is not None:
            cmd += ['-X', 'POST', '-H', 'Content-Type: application/json', '--data', data]
        cmd.append(url)
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = r.stdout.strip()
        if r.returncode == 0 and out:
            if not json_ok or out[0] in '{[':
                return r.stdout
            last_err = f'non-JSON ({out[:60]}…)'
        else:
            last_err = f'exit {r.returncode}: {r.stderr[:200]}'
        if attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f'curl {url} → {last_err}')


# ---------------------------------------------------------------------------
# Scryfall
# ---------------------------------------------------------------------------

def _local_card(name):
    """Carte depuis la base Scryfall locale (bulk SQLite, /opt/data/scryfall_bulk).
    Retourne None si absente ou si la base est indisponible → l'API prend le relais.
    Positionnable via SCRY_DB_PATH."""
    try:
        sys.path.insert(0, os.environ.get('SCRY_DB_PATH', '/opt/data/scryfall_bulk'))
        import scry_db
        return scry_db.get_card_with_img(name)
    except Exception:
        return None


def scryfall_batch(names, force=False):
    """Collection batch (70 max) avec fallback fuzzy pour les échecs (MDFC/Rooms).
    Local-first : résout via la base Scryfall locale, l'API ne traite que les manquants.
    force=True = chemin API pur (contourne aussi la base locale)."""
    out = []
    missing = names if force else []
    if not force:
        for n in names:
            c = _local_card(n)
            if c:
                out.append(c)
            else:
                missing.append(n)
    for i in range(0, len(missing), 70):
        chunk = missing[i:i + 70]
        key = _key('batch', sorted(chunk))

        def _fetch():
            body = json.dumps({'identifiers': [{'name': n} for n in chunk]})
            raw = _curl('https://api.scryfall.com/cards/collection', data=body)
            res = json.loads(raw)
            return res.get('data', [])

        data, _ = get('scryfall', key, _fetch, force=force)
        out.extend(data)
        time.sleep(0.1)
    # Fallback fuzzy pour les noms non résolus (MDFC avec '//' etc.)
    got = {c.get('name', '').split(' // ')[0] for c in out}
    for n in missing:
        base = n.split(' // ')[0]
        if base not in got:
            c = scryfall_fuzzy(n, force=force)
            if c:
                out.append(c)
            time.sleep(0.05)
    return out


def scryfall_named(name, force=False):
    """Recherche exacte (/cards/named?exact=). Local-first (base Scryfall locale)."""
    if not force:
        c = _local_card(name)
        if c:
            return c
    key = _key('named', name)

    def _fetch():
        url = f'https://api.scryfall.com/cards/named?exact={urllib.parse.quote(name)}'
        return json.loads(_curl(url))

    data, _ = get('scryfall', key, _fetch, force=force)
    return data


def scryfall_fuzzy(name, force=False):
    """Recherche fuzzy (/cards/named?fuzzy=) — fallback MDFC/Rooms.
    Local-first (préfixe « face avant » inclus) ; API sinon.
    Retourne None si Scryfall répond par un objet d'erreur (nom introuvable)."""
    if not force:
        c = _local_card(name)
        if c:
            return c
    key = _key('fuzzy', name)

    def _fetch():
        url = f'https://api.scryfall.com/cards/named?fuzzy={urllib.parse.quote(name)}'
        return json.loads(_curl(url))

    try:
        data, _ = get('scryfall', key, _fetch, force=force)
        if isinstance(data, dict) and data.get('object') == 'error':
            return None
        return data
    except Exception:
        return None


# ---------------------------------------------------------------------------
# EDHREC
# ---------------------------------------------------------------------------

def _edhrec_next_data(url):
    html = _curl(url, timeout=60, json_ok=False)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError(f'__NEXT_DATA__ introuvable sur {url}')
    return json.loads(m.group(1))


def edhrec_page(slug, force=False):
    """Page commander (/commanders/<slug>) — tag_counts, cardlists par type."""
    key = _key('page', slug)

    def _fetch():
        return _edhrec_next_data(f'https://edhrec.com/commanders/{slug}')

    data, _ = get('edhrec', key, _fetch, force=force)
    return data


def edhrec_tag(slug, tag, force=False):
    """Page tag (/commanders/<slug>/<tag>) — pool High Synergy du plan."""
    key = _key('tag', slug, tag)

    def _fetch():
        return _edhrec_next_data(f'https://edhrec.com/commanders/{slug}/{tag}')

    data, _ = get('edhrec', key, _fetch, force=force)
    return data


# ---------------------------------------------------------------------------
# Commander Spellbook
# ---------------------------------------------------------------------------

def spellbook_combos(query, force=False):
    """Recherche de combos via commanderspellbook.com/search/?q=... (le site, pas l'API v3
    qui est bloquée par Cloudflare). Les combos vivent dans __NEXT_DATA__.props.pageProps.combos.
    Retourne la liste brute de combos."""
    key = _key('combos', query)

    def _fetch():
        html = _curl(f'https://commanderspellbook.com/search/?q={urllib.parse.quote(query)}',
                     timeout=60, json_ok=False)
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            raise RuntimeError('__NEXT_DATA__ introuvable sur commanderspellbook.com')
        nd = json.loads(m.group(1))
        combos = nd.get('props', {}).get('pageProps', {}).get('combos', [])
        return combos if isinstance(combos, list) else []

    return get('spellbook', key, _fetch, force=force)[0]


# ---------------------------------------------------------------------------
# Moxfield (API v2 — Cloudflare → proxy r.jina.ai)
# ---------------------------------------------------------------------------

def moxfield_deck(public_id, force=False):
    """Liste d'un deck Moxfield. L'API directe est bloquée par Cloudflare → r.jina.ai
    (le JSON complet arrive dans le markdown après 'Markdown Content:')."""
    key = _key('deck', public_id)

    def _fetch():
        raw = _curl(f'https://r.jina.ai/https://api.moxfield.com/v2/decks/all/{public_id}',
                    timeout=90, json_ok=False)
        m = re.search(r'Markdown Content:\s*(\{.*\})', raw, re.S)
        if not m:
            raise RuntimeError(f'JSON Moxfield introuvable pour {public_id}')
        return json.loads(m.group(1))

    data, _ = get('moxfield', key, _fetch, force=force)
    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args or args[0] == '--help':
        print(__doc__)
        print('Commandes : --status | --prune | --refresh <source> <arg>')
        return
    if args[0] == '--status':
        st = status()
        if not st:
            print('Cache vide.')
        for src, e in sorted(st.items()):
            print(f'  {src:10} {e["entries"]:4} entrées · âge max {e["max_age_days"]} j')
        return
    if args[0] == '--prune':
        n = prune()
        print(f'Prune : {n} entrée(s) périmée(s) supprimée(s).')
        return
    if args[0] == '--refresh' and len(args) >= 2:
        source = args[1]
        if source == 'all':
            for src in TTL:
                print(f'  --refresh {src} (force)')
            print('Refresh complet : relancer chaque source avec sa clé.')
            return
        # Force re-fetch d'une source entière : on purge puis on note
        # (les wrappers re-fetcheront au prochain appel avec force=True)
        print(f'Refresh forcé : {source} — utilisez force=True dans les wrappers '
              f'ou supprimez data/cache/l1/{source}/')
        return
    print('Usage : --status | --prune | --refresh <source>')


if __name__ == '__main__':
    main()
