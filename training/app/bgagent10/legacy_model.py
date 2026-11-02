import torch
from torch import nn
from .encoding import SEMANTIC_DIM, entity_layout, action_descriptors

PRESETS = {'main':(384,8,8),'small':(192,4,6),'micro':(48,1,4)}

class PolicyModel(nn.Module):
    def __init__(self, catalog, layout, preset='small'):
        super().__init__()
        width,layers,heads=PRESETS[preset]; self.width=width; self.preset=preset
        self.register_buffer('runtime_to_stable',catalog.runtime_to_stable)
        self.register_buffer('semantics',catalog.semantics)
        self.entities=entity_layout(layout); self.layout=layout
        self.semantic=nn.Linear(SEMANTIC_DIM,width)
        self.identity=nn.Embedding(len(catalog.stable_ids),width,padding_idx=0)
        self.id_gate=nn.Parameter(torch.tensor(-2.0))
        self.id_dropout=nn.Dropout(.2)
        self.zone=nn.Embedding(9,width); self.owner=nn.Embedding(8,width); self.position=nn.Embedding(20,width)
        self.numeric=nn.Linear(64,width)
        self.global_encoder=nn.Linear(layout['GLOBAL_F']+15,width)
        layer=nn.TransformerEncoderLayer(width,heads,width*4,dropout=0,batch_first=True,norm_first=True)
        self.transformer=nn.TransformerEncoder(layer,layers,enable_nested_tensor=False)
        self.memory=nn.GRUCell(width,width)
        self.action_type=nn.Embedding(14,width); self.action_position=nn.Embedding(8,width); self.option=nn.Embedding(16,width)
        self.score=nn.Sequential(nn.Linear(width*4,width),nn.Tanh(),nn.Linear(width,1))
        self.value=nn.Linear(width,1); self.placement=nn.Linear(width,8)
        self.reconstruct_public=nn.Linear(width,layout['GLOBAL_F'])
        self.register_buffer('descriptors',torch.tensor(action_descriptors()))
        self.register_buffer('zones',torch.tensor([r[0] for r in self.entities]))
        self.register_buffer('owners',torch.tensor([r[1] for r in self.entities]))
        self.register_buffer('positions',torch.tensor([r[2] for r in self.entities]))

    def forward(self,features,cards,action_mask,hidden=None):
        if not torch.isfinite(features).all(): raise ValueError('nonfinite public observation')
        if not action_mask.bool().any(-1).all(): raise ValueError('no legal actions: not a policy decision')
        if (cards<0).any() or (cards>=len(self.runtime_to_stable)).any(): raise ValueError('unknown runtime card index')
        ids=self.runtime_to_stable[cards.long()]
        encoded=self.semantic(self.semantics[ids])+torch.sigmoid(self.id_gate)*self.id_dropout(self.identity(ids))
        nums=features.new_zeros((len(features),124,64))
        for i,(_,_,_,offset,n) in enumerate(self.entities):
            if n: nums[:,i,:n]=features[:,offset:offset+n]
        encoded=encoded+self.numeric(nums)+self.zone(self.zones)+self.owner(self.owners)+self.position(self.positions)
        context=self.global_encoder(features[:,:self.layout['GLOBAL_F']+15])
        tokens=torch.cat((context[:,None],encoded),1)
        # Opponent summaries and non-card options can exist without a card ID.
        valid=(cards!=0)|(nums.abs().sum(-1)>0)
        padding=torch.cat((torch.zeros((len(features),1),dtype=torch.bool,device=features.device),~valid),1)
        tokens=self.transformer(tokens,src_key_padding_mask=padding)
        if hidden is None: hidden=context.new_zeros((len(features),self.width))
        hidden=self.memory(tokens[:,0],hidden)
        d=self.descriptors
        action=self.action_type(d[:,0])+self.action_position(d[:,3])+self.option(d[:,4])
        source=tokens[:,d[:,1]]; target=tokens[:,d[:,2]]
        scores=self.score(torch.cat((hidden[:,None].expand(-1,245,-1),action[None].expand(len(features),-1,-1),source,target),-1)).squeeze(-1)
        logits=scores.masked_fill(~action_mask.bool(),-torch.inf)
        return logits,self.value(hidden).squeeze(-1),hidden,self.placement(hidden)

def observation_tensors(observations,device):
    return (torch.tensor([o['features'] for o in observations],dtype=torch.float32,device=device),
        torch.tensor([o['cards'] for o in observations],dtype=torch.long,device=device),
        torch.tensor([o['action_mask'] for o in observations],dtype=torch.bool,device=device))

def load_policy(checkpoint,device='cpu',rules_path=None):
    """Strict model load; no rules relabelling or optimizer/environment migration."""
    from .encoding import CardCatalog
    from .engine import DEFAULT_RULES,EnvironmentProcess
    saved=torch.load(checkpoint,map_location=device,weights_only=False)
    if saved.get('format')!='bgagent10-recurrent-ppo-v1': raise ValueError('unsupported model format')
    from .training import learning_contract
    if saved.get('contract')!=learning_contract(): raise ValueError('model learning semantics mismatch; audited migration required')
    rules_path=rules_path or DEFAULT_RULES
    catalog=CardCatalog(rules_path); driver=EnvironmentProcess(rules_path)
    try: metadata=driver.metadata
    finally: driver.close()
    if saved['binding']!=metadata['binding'] or saved['catalog']!=catalog.manifest(): raise ValueError('model rules/catalog mismatch')
    model=PolicyModel(catalog,metadata['layout'],saved['config']['model_preset']).to(device)
    model.load_state_dict(saved['model']); model.eval()
    return model

def predict_public(model,observation,hidden=None,deterministic=False):
    from .engine import public_input
    from torch.distributions import Categorical
    device=next(model.parameters()).device
    with torch.no_grad():
        logits,value,new_hidden,placement=model(*observation_tensors([public_input(observation)],device),hidden)
        dist=Categorical(logits=logits)
        action=logits.argmax(-1) if deterministic else dist.sample()
    return dict(action=int(action.item()),log_prob=float(dist.log_prob(action).item()),
        value=float(value.item()),placement=placement.softmax(-1)[0].tolist(),hidden=new_hidden)
