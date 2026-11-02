"""Strict local runtime validation. No checkpoint relabeling or automatic migration."""
import copy, hashlib, json, os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'app'))

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text('utf-8-sig'))
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp-'+str(os.getpid()))
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)
def verify_assets():
    for rel, expected in read(ROOT/'SOURCE_SHA256.json').items():
        data = (ROOT/rel).read_bytes()
        if rel == 'rules/bridge/backend.py':
            data = re.sub(rb"PYD_SHA='[^']+'", b"PYD_SHA='BUILD_REQUIRED'", data, count=1)
        if hashlib.sha256(data).hexdigest() != expected: raise ValueError('Source integrity mismatch: '+rel)
def resolve(path):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (ROOT/path).resolve()
def metadata():
    from bgagent10.engine import EnvironmentProcess
    worker = EnvironmentProcess(ROOT/'rules')
    try: return worker.metadata
    finally: worker.close()
def prepare(config):
    import torch
    from bgagent10.model import load_policy
    verify_assets()
    expected = read(ROOT/'build/runtime.json')
    meta = metadata()
    if meta['binding'] != expected['binding']:
        raise ValueError('Runtime binding changed; do not relabel existing checkpoints')
    config = copy.deepcopy(config); config['rules_path'] = str(ROOT/'rules')
    if config.get('live_data_root') or config.get('auxiliary_updates', 0):
        raise ValueError('This release supports offline simulator PPO only')
    if config.get('device') == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA unavailable')
    if config.get('resume_from'):
        path = resolve(config['resume_from'])
        load_policy(path, device='cpu', rules_path=ROOT/'rules')
        config['resume_from'] = str(path)
    for key in ('train_opponent_pool', 'eval_opponent_pool'):
        if config.get(key) is None: continue
        if not isinstance(config[key], list): raise ValueError('Use an explicit opponent list')
        for entry in config[key]:
            if entry['kind'] == 'checkpoint':
                path = resolve(entry['path'])
                if sha(path) != entry['sha256']: raise ValueError('Frozen opponent hash changed')
                load_policy(path, device='cpu', rules_path=ROOT/'rules')
                entry['path'] = str(path)
    return config
