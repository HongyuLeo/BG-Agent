"""Public-only guard for the frozen protected-card waiting-queue observation.

Source: engine.rs add_to_hand_impl/hand_protected/flush_hand_queue. Only trinkets,
quest rewards and three exact protected helpers can queue overflow; ordinary card
generation burns overflow and must not poison this counter.
"""
import re
from .live_parser import known,unknown

PROTECTED_KINDS={'trinket_lesser','trinket_greater','quest_reward'}
PROTECTED_IDS={'BG36_HERO_105p','BG24_HERO_100_Buddyt','BG24_HERO_100_Buddy_Gt'}
CAPACITY=10 # fixed solo8 public schema/config; no experimental hand expansion

def generation_bound(card):
    text=re.sub('<[^>]+>',' ',card.get('text','')).lower()
    generates=bool(re.search(r'\b(get|add|discover|return|copy|copies|steal|draw|receive)\b',text) or re.search(r'\b(move|put|fill)\b.*\bhand\b',text))
    if not generates:return False,0
    # Gold is a scalar resource, not a card delivered to the hand.
    if re.search(r'\b(?:get|gain)\s+\d+\s+gold\b',text) and not re.search(r'\b(card|minion|spell|gem|banana|coin|copy|copies)\b',text):return False,0
    matches=re.findall(r'\b(?:get|add|discover|return)\s+(\d+|a|an)\b',text)
    if len(matches)==1 and not re.search(r'\b(for each|repeat this|repeat until|repeat twice)\b',text):
        return True,1 if matches[0] in ('a','an') else int(matches[0])
    return True,None # ambiguous quantity: observe capacity during this source only

class PublicHandQueueGuard:
    def __init__(self,catalogue):self.catalogue=catalogue;self.reset(None)
    def reset(self,game_key):
        self.game_key=game_key;self.frames=[];self.uncertain=False;self.evidence=[];self.risk_batch=None;self.clear_proof=None;self.pending_discover={};self.awaiting_discover=[]
    def hand_count(self,ledger):
        return sum(ledger.val(e,'CONTROLLER')==ledger.observer and ledger.val(e,'ZONE') in ('HAND','3')
            and ledger.val(e,'CARDTYPE') not in ('HERO','3','ENCHANTMENT','6') for e in ledger.entities)
    def _mark(self,ledger,frame,reason):
        if not self.uncertain:self.risk_batch=ledger.option_batch
        self.uncertain=True
        if len(self.evidence)<8:self.evidence.append(dict(source_card=frame['card_id'],reason=reason,source=ledger.last_proof))
    def observe(self,ledger,text):
        if self.game_key!=ledger.game_key:self.reset(ledger.game_key)
        count=self.hand_count(ledger)
        if 'BLOCK_START' in text:
            m=re.search(r' Entity=(.+?) EffectCardId=',text);eid=ledger.ref(m[1]) if m else None
            leaf=ledger.entities.get(eid,{}).get('card_id',{});cid=leaf.get('value');card=self.catalogue.get(cid,{})
            effect=re.search(r' EffectCardId=(\S*)',text)
            if effect and effect[1] in self.catalogue:
                candidate=self.catalogue[effect[1]]
                if candidate.get('kind') in PROTECTED_KINDS or effect[1] in PROTECTED_IDS:cid=effect[1];card=candidate
            protected=card.get('kind') in PROTECTED_KINDS or cid in PROTECTED_IDS
            generates,bound=generation_bound(card)
            local=ledger.observer is not None and ledger.val(eid,'CONTROLLER')==ledger.observer
            text_rule=re.sub('<[^>]+>',' ',card.get('text','')).lower()
            discover=bool(re.search(r'(?:^|[.!:,]\s*)discover\b',text_rule))
            frame=dict(card_id=cid,active=bool(local and protected and generates),bound=bound,initial_count=count,discover=discover,batch=ledger.option_batch)
            self.frames.append(frame)
            if frame['active'] and (count>=CAPACITY or bound is not None and count+bound>CAPACITY):
                if not discover:self._mark(ledger,frame,'protected generating source may overflow fixed hand capacity')
        # A source with an unbound generation quantity may continue after filling
        # the last free slot. Never infer a positive count; mark it unknown.
        for frame in self.frames:
            if frame['active'] and not frame['discover'] and frame['bound'] is None and count>=CAPACITY:
                self._mark(ledger,frame,'protected generation quantity unbound after hand reached capacity')
        if ledger.choice and ledger.choice_owner==ledger.observer:
            candidates=[f for f in self.frames+self.awaiting_discover if f['active'] and f['discover']]
            if candidates:self.pending_discover[ledger.choice['id']]=candidates[-1];self.awaiting_discover=[]
        if 'DebugPrintEntitiesChosen()' in text and re.search(r' - id=\d+',text) and ledger.receipts:
            receipt=ledger.receipts[-1];frame=self.pending_discover.pop(receipt.get('choice_id'),None)
            selected=receipt.get('count')
            if frame and type(selected) is not int:self._mark(ledger,frame,'protected Discover receipt count missing; queue consequence unknown')
            elif frame and selected>0 and (count>=CAPACITY or frame['bound'] is None or count+frame['bound']>CAPACITY):
                self._mark(ledger,frame,'own protected Discover acknowledged; selected card may wait behind a full hand')
        if 'BLOCK_END' in text and self.frames:
            frame=self.frames.pop()
            if frame['active'] and frame['discover'] and frame not in self.pending_discover.values():self.awaiting_discover.append(frame)
    def fact(self,ledger):
        if not ledger.saw_create:return unknown('missing CREATE_GAME; initial hand queue not established')
        # Opening a Discover menu has not generated its selected card yet. Do
        # not deadlock the model's mandatory choice when the prior queue was0.
        # If a fresh decision batch arrives without a choice, the unbound source
        # may instead have directly delivered cards; keep that capacity risk.
        if self.awaiting_discover and ledger.options_complete and not ledger.choice:
            for frame in self.awaiting_discover:
                if ledger.option_batch!=frame['batch'] and self.hand_count(ledger)>=CAPACITY:self._mark(ledger,frame,'protected source ended without a bound Discover receipt; queue quantity unresolved')
            if any(ledger.option_batch!=f['batch'] for f in self.awaiting_discover):self.awaiting_discover=[]
        if self.uncertain:
            # Native flush_hand_queue delivers every waiting card until either
            # the queue is empty or hand==10. A NEW sealed recruit decision batch
            # with spare capacity and no active source therefore proves queue0.
            if ledger.options_complete and not ledger.collecting and not self.frames and ledger.option_batch!=self.risk_batch and self.hand_count(ledger)<CAPACITY:
                self.uncertain=False;self.clear_proof=ledger.last_proof
            else:return unknown('protected full-hand generation can leave a nonzero waiting queue; public count/flush evidence required')
        if self.clear_proof:return known(0,self.clear_proof,'new sealed decision batch with spare hand capacity; frozen flush_hand_queue exhausts queue before decision')
        return known(0,{'create':ledger.create_proof},'initial queue empty; no observed local protected-card overflow opportunity')
