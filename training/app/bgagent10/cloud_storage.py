"""Bound checkpoint growth within this cloud run; preserve recovery evidence."""
import json,re,shutil,time
from pathlib import Path

def pin(checkpoint):
    Path(str(checkpoint)+'.protected').touch(exist_ok=True)

def low_space(run,config):
    return shutil.disk_usage(run).free < config.get('min_free_disk_gb',2)*1024**3

def prune(run,config,current):
    candidate=Path(run)/'checkpoints'
    if candidate.is_symlink():raise ValueError('Checkpoint directory cannot be a symlink')
    directory=candidate.resolve()
    if not directory.is_relative_to(Path(run).resolve()):raise ValueError('Checkpoint directory escaped run')
    if not directory.is_dir():return []
    paths=sorted((p for p in directory.iterdir() if p.is_file() and not p.is_symlink()
        and re.fullmatch(r'step-\d+\.pt',p.name)),key=lambda p:int(p.stem.split('-')[1]),reverse=True)
    keep=max(2,int(config.get('keep_checkpoints',5)))
    protected={Path(current).resolve()}
    for key in ('train_opponent_pool','eval_opponent_pool'):
        for entry in config.get(key) or []:
            if isinstance(entry,dict) and entry.get('kind')=='checkpoint':protected.add(Path(entry['path']).resolve())
    removed=[]
    for path in paths[keep:]:
        if path.resolve() in protected or Path(str(path)+'.protected').exists():continue
        size=path.stat().st_size
        # Only named checkpoints inside this run; never source/resume/opponent files.
        if path.resolve().parent!=directory:raise ValueError('Checkpoint retention path escaped')
        path.unlink();removed.append({'name':path.name,'bytes':size})
    if removed:
        with (Path(run)/'storage.jsonl').open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'time':time.time(),'removed':removed,'retained_latest':keep})+'\n')
    return removed
