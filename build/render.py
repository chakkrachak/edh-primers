#!/usr/bin/env python3
"""Mini-moteur de template maison — zéro dépendance, approche par pile.
Support : {{ var }}, {{ var|filter }}, {% for x in seq %}…{% endfor %},
          {% if expr %}…{% else %}…{% endif %} (imbrication incluse)
Filtres : escape, mana, safe."""
import re
import html as H

TOKEN_RE = re.compile(r'({%.*?%}|{{.*?}})', re.S)

def _lookup(path, ctx):
    parts = str(path).split('.')
    val = ctx
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p, '')
        elif isinstance(val, (list, tuple)) and p.lstrip('-').isdigit():
            val = val[int(p)]
        else:
            val = getattr(val, p, '') if not isinstance(val, (str, int, float)) else ''
    return val

def _eval_expr(expr, ctx):
    expr = expr.strip()
    if '|' in expr:
        parts = [p.strip() for p in expr.split('|')]
        val = _lookup(parts[0], ctx)
        for f in parts[1:]:
            if f == 'escape':
                val = H.escape(str(val))
            elif f == 'safe':
                pass
            elif f == 'mana':
                val = mana_symbols(str(val))
            else:
                raise ValueError(f"filtre inconnu: {f}")
        return val
    return _lookup(expr, ctx)

def _truthy(cond, ctx):
    cond = cond.strip()
    try:
        if re.search(r'==|!=|>=|<=|>|<| and | or | not ', cond):
            def sub_lookup(m):
                key = m.group(0).strip()
                v = _lookup(key, ctx)
                return repr(v) if isinstance(v, str) else str(v)
            expr = re.sub(r'[A-Za-z_][\w.]*', sub_lookup, cond)
            return bool(eval(expr, {"__builtins__": {}}))
    except Exception:
        pass
    return bool(_lookup(cond, ctx))

def render(template, ctx):
    tokens = TOKEN_RE.split(template)
    out = []
    stack = []      # ['for', var, seq, body[]] | ['if', cond, body[], else_body]
    raw = 0         # >0 : on collecte brut dans le body de la boucle parente

    def in_loop():
        return bool(stack) and stack[-1][0] == 'for'

    for tok in tokens:
        if tok.startswith('{%'):
            tag = tok[2:-2].strip()

            if raw > 0:
                # sous-bloc brut : tout est collecté, on suit la profondeur
                if tag.startswith(('if ', 'for ')):
                    raw += 1
                elif tag in ('endif', 'endfor'):
                    raw -= 1
                stack[-1][3].append(tok)
                continue

            if tag.startswith('for '):
                m = re.match(r'for\s+(\w+)\s+in\s+(.+)', tag)
                if in_loop():
                    # for imbriqué dans une boucle : gardé brut dans le body parent
                    stack[-1][3].append(tok)
                    raw += 1
                else:
                    stack.append(['for', m.group(1), m.group(2).strip(), []])
            elif tag.startswith('if '):
                if in_loop():
                    # if dans une boucle : gardé brut dans le body parent
                    stack[-1][3].append(tok)
                    raw += 1
                else:
                    stack.append(['if', tag[3:].strip(), None, [], None])  # [type, cond, _, body, else_body]
            elif tag == 'else':
                blk = stack[-1]
                blk[4] = ''.join(blk[3]) if isinstance(blk[3], list) else blk[3]
                blk[3] = []
            elif tag == 'endif':
                blk = stack.pop()
                if blk[4] is not None:
                    main_body, else_body = blk[4], ''.join(blk[3]) if isinstance(blk[3], list) else (blk[3] or '')
                else:
                    main_body, else_body = ''.join(blk[3]) if isinstance(blk[3], list) else (blk[3] or ''), ''
                result = render(main_body, ctx) if _truthy(blk[1], ctx) else render(else_body, ctx)
                if stack:
                    stack[-1][3].append(result)
                else:
                    out.append(result)
            elif tag == 'endfor':
                blk = stack.pop()
                body = ''.join(blk[3]) if isinstance(blk[3], list) else blk[3]
                seq = _lookup(blk[2], ctx) or []
                parts = []
                for item in seq:
                    sub = dict(ctx)
                    sub[blk[1]] = item
                    parts.append(render(body, sub))
                result = ''.join(parts)
                if stack:
                    stack[-1][3].append(result)
                else:
                    out.append(result)
            else:
                raise ValueError(f"tag inconnu: {tag}")

        elif tok.startswith('{{'):
            if stack:
                stack[-1][3].append(tok)
            else:
                out.append(str(_eval_expr(tok[2:-2], ctx)))
        else:
            if stack:
                stack[-1][3].append(tok)
            else:
                out.append(tok)

    if stack:
        raise ValueError(f"bloc non fermé: {stack[-1][0]}")
    return ''.join(out)

def mana_symbols(text):
    if not text:
        return ""
    def repl(m):
        inner = m.group(1).strip()
        code = inner.replace("/", "")
        return (f'<img src="https://svgs.scryfall.io/card-symbols/{code}.svg" '
                f'alt="{H.escape(inner)}" title="{H.escape(inner)}" class="ms"/>')
    return re.sub(r'\{([^}]+)\}', repl, text)
