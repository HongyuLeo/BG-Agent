"""Versioned exhibition decoder. No weights, rewards, or engine masks change.

The model still sees the complete engine observation. These additional execution
constraints use only the player's public history and are logged separately.
"""
import hashlib
import json
import itertools

VERSION = 'turn-end-fixed-formation-v2'

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class ExhibitionPolicy:
    def __init__(self):
        self.turn=None
        self.actions=0
        self.edges=set()
        self.contexts={}
        self.interventions=0
        self.plan=None
        self.plan_index=0
        self.plan_reason=None

    def prepare(self, observation):
        features=observation['features'];cards=observation['cards']
        if (len(features),len(cards),len(observation['action_mask']))!=(3227,124,245):
            raise ValueError('模拟决策观察格式不匹配')
        if self.turn!=features[0]:
            self.turn=features[0];self.actions=0;self.edges=set();self.contexts={}
            self.plan=None;self.plan_index=0;self.plan_reason=None
        board=tuple((cards[19+i],tuple(features[68+31*i:68+31*(i+1)]))
                    for i in range(7) if features[68+31*i])
        # A fixed board retains its budget across freezing, buying and menus.
        # Actual board membership/stat changes open a fresh arrangement budget.
        context=fingerprint(sorted(board))
        state=fingerprint(observation)
        record=self.contexts.setdefault(context,{'layouts':set(),'moves':0})
        record['layouts'].add(board)
        allowed=[bool(x) for x in observation['action_mask']]
        excluded={}
        for action,legal in enumerate(allowed):
            if not legal:continue
            reason=None
            if self.actions>=128 and allowed[0] and action!=0:
                reason='turn_action_budget'
            elif (action==2 or action>=196) and (state,action) in self.edges:
                reason='repeated_public_state_action'
            elif action>=196:
                source,target=divmod(action-196,7)
                if source>=len(board) or target>=len(board) or source==target:
                    raise ValueError('后端换位合法动作与公开阵容不一致')
                reason='formation_deferred_until_end_turn'
            if reason:allowed[action]=False;excluded[action]=reason
        if not any(allowed):
            raise ValueError('模拟防循环决策没有可推进的合法动作；保留诊断，不伪造动作')
        return allowed,excluded,state,context

    @staticmethod
    def board(observation):
        f=observation['features'];c=observation['cards']
        return tuple((c[19+i],tuple(f[68+31*i:68+31*(i+1)]))
                     for i in range(7) if f[68+31*i])

    def make_plan(self, logits, observation):
        """One public-state scoring pass, then a canonical insertion path.

        This is a decoder heuristic, NOT a combat-value search or PPO sample.
        Every insertion fixes a new prefix; no decided position is revisited.
        """
        board=self.board(observation);n=len(board)
        scores=logits.detach().cpu().reshape(-1).tolist()
        legal=observation['action_mask'];identity=tuple(range(n))
        best=identity;best_key=(0.,0)
        for order in itertools.permutations(range(n)):
            gain=0.;changed=0
            for target,source in enumerate(order):
                if board[source]==board[target]:continue
                a=196+source*7+target
                if not legal[a]:gain=float('-inf');break
                # Retaining a slot is the baseline. Require a positive margin
                # over END rather than moving just because another move exists.
                gain+=scores[a]-scores[0]-1.;changed+=1
            key=(gain,-changed)
            if key>best_key:best=order;best_key=key
        current=list(identity);steps=[]
        for target,source_id in enumerate(best):
            source=current.index(source_id)
            if source==target:continue
            before=tuple(board[i] for i in current)
            action=196+source*7+target
            current.insert(target,current.pop(source))
            after=tuple(board[i] for i in current)
            if before!=after:steps.append((before,action))
        self.plan=steps;self.plan_index=0;self.plan_reason='fixed_plan'

    def planned_action(self, observation):
        if self.plan_index<len(self.plan):
            expected,action=self.plan[self.plan_index]
            if self.board(observation)==expected and observation['action_mask'][action]:
                return action
            # Drift cancels the old plan; never replan repeatedly in one turn.
            self.plan_index=len(self.plan);self.plan_reason='public_state_changed_plan_cancelled'
        if not observation['action_mask'][0]:
            raise ValueError('站位计划结束后无法结束回合；保存现场，不重做站位')
        return 0

    def choose(self, logits, observation, deterministic):
        import torch
        allowed,excluded,state,context=self.prepare(observation)
        raw=torch.distributions.Categorical(logits=logits)
        filtered=logits.masked_fill(~torch.tensor([allowed],device=logits.device),-torch.inf)
        execution=torch.distributions.Categorical(logits=filtered)
        preferred=int(logits.argmax(-1).item())
        selected=int(filtered.argmax(-1).item()) if deterministic else int(execution.sample().item())
        planning=self.plan is not None or selected==0
        if planning:
            if self.plan is None:self.make_plan(logits,observation)
            selected=self.planned_action(observation)
            excluded.pop(selected,None)
        intervention=preferred!=selected
        self.interventions+=int(intervention)
        info=dict(version=VERSION,mode='greedy' if deterministic else 'sample',
                  raw_preferred_action=preferred,selected_action=selected,
                  raw_selected_probability=float(raw.probs[0,selected]),
                  execution_probability=None if planning else (1.0 if deterministic else float(execution.probs[0,selected])),
                  formation_phase='fixed_plan' if planning else 'economy',
                  formation_plan_steps=len(self.plan) if self.plan is not None else 0,
                  formation_plan_index=self.plan_index,formation_plan_reason=self.plan_reason,
                  excluded_actions=[dict(action=a,reason=reason) for a,reason in excluded.items()],
                  excluded_probability_mass=float(raw.probs[0,[*excluded]].sum()) if excluded else 0.0,
                  preferred_action_excluded=intervention)
        # Caller commits only after an authoritative successful environment step.
        return selected,info,(state,context,selected)

    def commit(self, ticket):
        state,context,action=ticket
        self.edges.add((state,action));self.actions+=1
        if action>=196:
            self.contexts[context]['moves']+=1
            self.plan_index+=1
