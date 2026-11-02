"""Explicit named offering entry; source offering qualification is not full rule certification."""
from pathlib import Path
import json,sys
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P/'bridge'))
from backend import Backend,target_roster_binding
def create_target37_backend(seed=97,**kwargs):
 binding=json.loads((P/'TARGET_ROSTER_BINDING.json').read_text('utf8'))
 if binding['manifest']['target_build']!='37.0.0.255130':raise ValueError('This entry is frozen to37.0.0.255130')
 config=kwargs.pop('config',{}).copy()
 if 'target_roster' in config or config.get('hero_pool') or config.get('experimental_mode'):raise ValueError('Do not override the named offering contract')
 config['target_roster']=target_roster_binding(binding['manifest'],binding['manifest_sha256'])
 return Backend(seed,config,**kwargs)
if __name__=='__main__':
 b=create_target37_backend();o=b.observe();print(json.dumps({'schema':o['schema'],'active_manifest_sha256':b._config['target_roster']['manifest_sha256'],'actions':sum(o['action_mask']),'full37':False}))
