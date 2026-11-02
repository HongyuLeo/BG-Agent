"""Versioned stable identities and offline rule-text features (no LLM at runtime).

Text feature hashing is shared across cards, not a card-ID hash. Mechanics extraction
is deliberately marked incomplete: complex callbacks retain source text and unknown.
"""
import hashlib, json, re
from pathlib import Path
import torch

SEMANTIC_VERSION = 'numeric-text-mechanic-v1-incomplete-callbacks'
SEMANTIC_DIM = 192

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':')).encode('utf8')).hexdigest()

def card_semantics(card):
    vec = [0.] * SEMANTIC_DIM
    for i,key in enumerate(('tier','atk','hp','armor','cost')): vec[i] = float(card.get(key,0))/10
    vec[5] = float(bool(card.get('normal')))
    text = re.sub('<[^>]+>', ' ', card.get('text','')).lower()
    # Explicit event/condition/selector/operation/duration/limit signals.
    groups = [('battlecry','deathrattle','after you buy','after you play','end of your turn','start of combat'),
        ('if','whenever','after','before'),('friendly','enemy','other','random','all','adjacent'),
        ('give','gain','summon','destroy','discover','get','set','double'),
        ('permanently','this combat','until next turn','this turn'),('once','twice','first','each')]
    cursor = 8
    for group in groups:
        for term in group: vec[cursor] = float(term in text); cursor += 1
    vec[7] = 1.0 # Unknown callback structure remains explicit; no claim of complete parser.
    for number in re.findall(r'\d+', text): vec[6] += min(float(number),100)/100
    tokens = re.findall(r'[a-z]+|\d+', text)
    tokens += ['kind:'+card.get('kind','unknown')]
    tokens += ['race:'+x for x in card.get('races',[])] + ['kw:'+x for x in card.get('keywords',[])]
    for token in tokens:
        h = hashlib.sha256(token.encode()).digest()
        vec[64+int.from_bytes(h[:2],'little')%128] += (1 if h[2]&1 else -1)/max(len(tokens),1)**.5
    return vec

class CardCatalog:
    def __init__(self, rules):
        path = Path(rules)/'source/crates/taverngym/data/cards.json'
        self.source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        cards = json.loads(path.read_text('utf8'))['cards']
        self.runtime_ids = ['']+[c['id'] for c in cards] # Native raw.cards enumerate, confirmed cards.rs.
        self.stable_ids = ['']+sorted(c['id'] for c in cards)
        stable = {key:i for i,key in enumerate(self.stable_ids)}
        self.runtime_to_stable = torch.tensor([stable[x] for x in self.runtime_ids])
        by_id = {c['id']:c for c in cards}
        self.semantics = torch.tensor([[0.]*SEMANTIC_DIM]+[card_semantics(by_id[x]) for x in self.stable_ids[1:]])
        self.mapping_hash = digest(self.runtime_ids)

    def manifest(self):
        return {'semantic_version':SEMANTIC_VERSION,'source_sha':self.source_sha,
            'mapping_hash':self.mapping_hash,'stable_ids':self.stable_ids,'runtime_ids':self.runtime_ids}

def entity_layout(layout):
    # tuple = (zone, owner-relative, positional slot, float offset, float width)
    result = [(1,0,i,-1,0) for i in range(19)] # hero/powers/deity/source/quests/secrets
    offset = layout['GLOBAL_F']+6+9
    for zone,n,width in ((2,7,layout['MINION_F']),(3,10,layout['ITEM_F']),
                         (4,8,layout['ITEM_F']),(5,16,layout['ITEM_F'])):
        for i in range(n): result.append((zone,0,i,offset,width)); offset += width
    result += [(6,0,i,-1,0) for i in range(8)]
    for i in range(7): result.append((7,i+1,0,offset,9)); offset += 9
    for i in range(7):
        for j in range(7): result.append((8,i+1,j,offset,layout['MINION_F'])); offset += layout['MINION_F']
    if len(result)!=124 or offset!=3227: raise ValueError('entity layout drift')
    return result

def action_descriptors():
    # type, source card-slot (+1, zero=context), target (+1), position, option
    out = [(i,0,0,0,0) for i in range(4)]
    out += [(4,2+i,0,0,0) for i in range(2)] + [(5,4,0,0,0),(6,0,0,0,0)]
    out += [(7,37+i,0,0,0) for i in range(8)]
    out += [(8,20+i,0,0,0) for i in range(7)]
    out += [(9,20+i,0,0,0) for i in range(7)]
    out += [(10,45+i,0,0,i) for i in range(16)]
    out += [(11,27+h,0,p,0) for h in range(10) for p in range(8)]
    out += [(12,27+h,20+b,b,0) for h in range(10) for b in range(7)]
    out += [(13,20+a,20+b,b,0) for a in range(7) for b in range(7)]
    assert len(out)==245
    return out
