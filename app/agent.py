"""Read-only, deterministic inventory tool. Never infer a SKU from a near match."""
import json
import re
from pathlib import Path

INVENTORY = json.loads((Path(__file__).parent.parent / 'data/inventory.json').read_text())
WORDS = dict(zip('zero one two three four five six seven eight nine'.split(), '0123456789'))


def normalize(text):
    text = text.lower().replace('s.k.u.', 'sku').replace('s k u', 'sku')
    return re.sub(r'\b(?:' + '|'.join(WORDS) + r')\b', lambda m: WORDS[m[0]], text)


def answer(text, context=None):
    q = normalize(text)
    context = context or {}
    context = {k: v for k, v in context.items() if k in {'sku', 'aisle', 'pending_aisle', 'pending', 'intent'}}
    if not isinstance(context.get('sku'), str) or context.get('sku') not in {i['sku'] for i in INVENTORY['items']}:
        context.pop('sku', None)
    for key in ('aisle', 'pending_aisle'):
        if type(context.get(key)) is not int:
            context.pop(key, None)
    def result(reply, status='clarify', **extra):
        return dict(reply=reply, status=status, context=context, snapshot=INVENTORY['snapshot'], **extra)
    if re.search(r'\b(cancel|reset|start over)\b', q):
        context = {}
        return result('Cleared. Ask for a stock count or bin location.', 'reset')
    if re.search(r'\b(delete|remove|reserve|allocate|adjust|update|move|pick|ship)\b', q):
        return result('I can only check inventory. For stock changes, use the warehouse management system.', 'unsupported')
    if re.search(r'\b(repeat|say that again)\b', q) and context.get('sku'):
        replay = answer(('where is it' if context.get('intent') == 'location' else 'how many units of it'), context)
        replay['status'] = 'repeat'
        return replay
    ids = re.findall(r'\bsku[\s-]*((?:\d[\s-]*){4})\b', q)
    ids = list(dict.fromkeys('SKU-' + re.sub(r'\D', '', v) for v in ids))
    if len(ids) > 1:
        return result('Please ask about one SKU at a time.')
    aisle_match = re.search(r'\baisle\s+(\d+)\b', q)
    aisle = int(aisle_match[1]) if aisle_match else None
    if re.search(r'\b(all aisles|everywhere|whole warehouse)\b', q):
        aisle = None
    candidates = [i for i in INVENTORY['items'] if i['sku'] in ids] if ids else [i for i in INVENTORY['items'] if any(a in q for a in [i['name'].lower(), *i['aliases']])]
    if ids and not candidates:
        return result(f"I couldn't find {ids[0]}. Please repeat the four SKU digits.", 'not_found')
    if len(candidates) > 1:
        context = {'pending_aisle': aisle, 'pending': True, 'intent': 'location' if re.search(r'\b(where|location|bin|find)\b', q) else 'stock'}
        return result('Which wrap size: 18 inch, SKU 4821, or 12 inch, SKU 4822?')
    if not candidates and context.get('pending') and re.search(r'\b(18|12)\s*inch\b', q):
        candidates = [i for i in INVENTORY['items'] if f"{re.search(r'(18|12)', q)[0]} inch" in i['name']]
    if not candidates and context.get('sku') and re.search(r'\b(it|that|aisle|available|where)\b', q):
        candidates = [i for i in INVENTORY['items'] if i['sku'] == context['sku']]
    intent = 'location' if re.search(r'\b(where|location|bin|find)\b', q) else (context.get('intent', 'stock') if context.get('pending') else 'stock')
    if not candidates:
        return result('Say a four-digit SKU or product name, for example: how many units of SKU 4821 are in aisle 7?')
    item = candidates[0]
    if not aisle_match and not re.search(r'\b(all aisles|everywhere|whole warehouse)\b', q):
        aisle = context.get('pending_aisle', context.get('aisle')) if not ids else context.get('pending_aisle')
    bins = [b for b in item['bins'] if aisle is None or b['aisle'] == aisle]
    context = {'sku': item['sku'], 'aisle': aisle, 'intent': intent}
    if not bins:
        return result(f"No stock record for {item['sku']} in aisle {aisle}. Ask where it is in all aisles.", 'no_location')
    on_hand = sum(b['on_hand'] for b in bins)
    reserved = sum(b['reserved'] for b in bins)
    held = sum(b['held'] for b in bins)
    available = on_hand - reserved - held
    scope = f'in aisle {aisle}' if aisle is not None else 'across the warehouse'
    locations = ', '.join(b['bin'] for b in bins)
    reply = (f"{item['sku']}: bins {locations}. {available} units available {scope}." if intent == 'location' else
             f"{item['sku']} has {on_hand} units on hand {scope}. {available} available, {reserved} reserved, {held} on hold. Bins {locations}.")
    if available == 0:
        reply += ' No units are available to pick.'
    reply += ' This is a demo snapshot, not live stock.'
    return result(reply, 'found', item=item['name'], bins=bins, totals=dict(on_hand=on_hand, available=available, reserved=reserved, held=held))
