"""Read-only CPU checkpoint metadata; never infer game counts from filenames."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import os
import torch


def _stat_key(stat):
    # Windows Python 3.12 stat/fstat can disagree on ctime semantics for the
    # same untouched file. Identity, size, mtime and byte hashes are compared.
    return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)


def _number(value,label):
    if type(value) is not int or value<0:raise ValueError('模型元数据中的'+label+'无效')
    return value


def _resolved(path):
    try:return str(Path(path).expanduser().resolve())
    except (TypeError,ValueError,OSError):return None


def _inspect_checkpoint(path):
    """Load trusted local .pt on CPU, hashing the exact opened stable file."""
    path=Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower()!='.pt':raise ValueError('请选择已保存的 .pt 模型检查点')
    before=path.stat()
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        if _stat_key(opened)!=_stat_key(before):raise ValueError('模型正在保存，请稍后重新读取')
        digest=hashlib.sha256()
        while chunk:=stream.read(1024*1024):digest.update(chunk)
        stream.seek(0)
        saved=torch.load(stream,map_location='cpu',weights_only=False)
        stream.seek(0);verified=hashlib.sha256()
        while chunk:=stream.read(1024*1024):verified.update(chunk)
        if verified.digest()!=digest.digest():raise ValueError('模型读取期间字节发生变化，请稍后重试')
        after_open=os.fstat(stream.fileno())
    after=path.stat()
    if _stat_key(before)!=_stat_key(after) or _stat_key(opened)!=_stat_key(after_open):
        raise ValueError('模型在读取期间发生变化，请选择已完成保存的检查点')
    if not isinstance(saved,dict) or saved.get('format')!='bgagent10-recurrent-ppo-v1':raise ValueError('不支持的模型检查点格式')
    counters=saved.get('counters',{});config=saved.get('config',{})
    games=_number(counters.get('completed_games'),'累计训练局数');updates=_number(counters.get('updates'),'参数更新次数')
    preset=config.get('model_preset')
    if not isinstance(preset,str) or not preset:raise ValueError('模型结构标记缺失')
    model=saved.get('model',{});identity=model.get('identity.weight')
    width=int(identity.shape[1]) if isinstance(identity,torch.Tensor) and identity.ndim==2 else None
    layers={int(key.split('.')[2]) for key in model if key.startswith('transformer.layers.') and len(key.split('.'))>3 and key.split('.')[2].isdigit()}
    # The preset's exact architecture is still verified by unchanged load_policy.
    heads={'main':8,'small':6,'micro':4}.get(preset)
    source=str(path);sidecar=path.with_suffix('.json');file_sha=digest.hexdigest()
    if sidecar.is_file():
        try:
            record=json.loads(sidecar.read_text('utf-8-sig'))
            if record.get('sha256')==file_sha and _resolved(record.get('snapshot'))==str(path) and record.get('source'):
                source=_resolved(record['source']) or str(path)
        except (OSError,ValueError,TypeError):pass
    evaluation=copy.deepcopy(saved.get('evaluation'));attribution='none';evaluation_checkpoint=None
    if isinstance(evaluation,dict):
        evaluation_checkpoint=evaluation.get('checkpoint');attribution='unverified'
        evaluated_updates=evaluation.get('updates');evaluated_games=evaluation.get('completed_games')
        if (type(evaluated_updates) is int and evaluated_updates!=updates) or (type(evaluated_games) is int and evaluated_games!=games):
            attribution='other_checkpoint'
        elif (_resolved(evaluation_checkpoint) in {str(path),source} and type(evaluated_updates) is int
                and type(evaluated_games) is int and evaluated_updates==updates and evaluated_games==games):
            attribution='current'
    return {'path':str(path),'source':source,'sha256':file_sha,'stat_key':list(_stat_key(after)),
        'completed_games':games,'updates':updates,'preset':preset,'width':width,'transformer_layers':len(layers) if layers else None,
        'attention_heads':heads,'memory':'GRUCell','evaluation':evaluation,'evaluation_attribution':attribution,
        'evaluation_checkpoint':evaluation_checkpoint,'binding':copy.deepcopy(saved.get('binding')),
        'catalog':copy.deepcopy(saved.get('catalog')),'contract':copy.deepcopy(saved.get('contract')),
        'quarantined_games':len(saved.get('quarantine_manifest') or []),'metadata_only':True}


def inspect_checkpoint(path):
    """Public metadata interface with readable errors; no policy execution."""
    try:return _inspect_checkpoint(path)
    except ValueError:raise
    except Exception as exc:raise ValueError('无法读取模型元数据：'+str(exc)) from exc


def format_summary(info):
    """Pure Chinese presentation; no filesystem reads or strength claims."""
    lines=[f"累计已完成训练 {info.get('completed_games','未知')} 局 · 参数更新 {info.get('updates','未知')} 次 · {info.get('preset','未知')} 模型"]
    evaluation=info.get('evaluation');attribution=info.get('evaluation_attribution')
    if not isinstance(evaluation,dict):lines.append('所选模型未保存当前规则绑定的评估结果')
    else:
        name=Path(str(info.get('evaluation_checkpoint') or '未知检查点')).name
        label='对应当前模型' if attribution=='current' else '针对其它检查点，非当前模型' if attribution=='other_checkpoint' else '归属未核实，不作为当前模型评估'
        lines.append(f"评估：{name}（{label}）；样本 {evaluation.get('games','未知')} 局，对手 {evaluation.get('opponent','未记录')}")
        if evaluation.get('mean_rank') is not None:
            lines.append(f"平均名次 {evaluation['mean_rank']}，区间 [{evaluation.get('ci_low','未知')}, {evaluation.get('ci_high','未知')}]")
    if info.get('quarantined_games'):lines.append(f"历史隔离 {info['quarantined_games']} 局；原记录保留")
    lines.append('训练局数不等于棋力证明；开始实战后整局使用固定模型副本。')
    return '\n'.join(lines)


def latest_checkpoint(training_root):
    """Return a saved Path or None; no run/process/control changes or scanning pt."""
    root=Path(training_root).expanduser().resolve()
    runs=root if root.name=='runs' else root/'runs' if (root/'runs').is_dir() else root/'data/runs'
    if not runs.is_dir():return None
    candidates=[]
    for run in runs.iterdir():
        if not run.is_dir() or run.name.lower().startswith('engineering'):continue
        status=run/'status.json'
        try:
            record=json.loads(status.read_text('utf-8-sig'));value=record.get('checkpoint')
            if not value:continue
            path=Path(value);path=path if path.is_absolute() else run/path
            path=path.resolve()
            if path.suffix.lower()!='.pt' or not path.is_file():continue
            stat=path.stat();candidates.append((stat.st_mtime_ns,status.stat().st_mtime_ns,str(path),path))
        except (OSError,ValueError,TypeError,AttributeError):continue
    return max(candidates,key=lambda item:item[:3])[3] if candidates else None
