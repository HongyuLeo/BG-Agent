#!/usr/bin/env python3
"""Linux-only training launcher; status/export use the standard library only."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
TERMINAL = {'paused', 'stopped', 'completed', 'failed'}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text('utf-8-sig'))
    except (OSError, ValueError):
        return default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def launch_lock(root):
    if sys.platform != 'linux':
        raise RuntimeError('start/pause require Linux; this launcher never starts Windows training.')
    import fcntl
    path = Path(root) / 'data/runs/.cloud-launch.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def process_identity(pid, proc_root=Path('/proc')):
    """Linux stat field22 plus boot_id; never trust PID existence alone."""
    try:
        data = (Path(proc_root)/str(int(pid))/'stat').read_text()
        fields = data[data.rfind(')')+2:].split()
        if fields[0] in ('Z', 'X'):
            return None
        return {'starttime_ticks': fields[19],
                'boot_id': (Path(proc_root)/'sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, ValueError, IndexError, TypeError):
        return None


def is_alive(launch):
    expected = launch.get('identity')
    return bool(expected and process_identity(launch.get('pid')) == expected)


def runs(root):
    return sorted((p for p in (Path(root)/'data/runs').glob('*')
                   if p.is_dir() and (p/'cloud_launch.json').is_file()), reverse=True)


def resolve_run(root, value='latest'):
    if value == 'latest':
        options = runs(root)
        if not options:
            raise ValueError('No cloud training run exists.')
        return options[0]
    path = Path(value).expanduser()
    if not path.is_absolute() and (Path(root)/'data/runs'/path).is_dir():
        path = Path(root)/'data/runs'/path
    path = path.resolve()
    if not (path/'cloud_launch.json').is_file():
        raise ValueError('Not a cloud training run: '+str(path))
    return path


def published_checkpoint(run):
    """Do not glob .pt files: only the trainer's published boundary is exportable."""
    status = read_json(Path(run)/'status.json', {})
    value = status.get('checkpoint')
    if not value:
        raise ValueError('No trainer-published checkpoint yet; wait for a saved boundary.')
    path = Path(value)
    if not path.is_absolute():
        path = Path(run)/path
    path = path.resolve()
    if not path.is_file() or path.suffix != '.pt':
        raise ValueError('Published checkpoint is missing or invalid.')
    return path


def checkpoint_games(path):
    # Trusted local package checkpoint only. No model construction or CUDA use.
    import torch
    value = torch.load(path, map_location='cpu', weights_only=False)
    count = value.get('counters', {}).get('completed_games')
    if type(count) is not int or count < 0:
        raise ValueError('Checkpoint has no valid cumulative completed_games counter.')
    return count


def prepare_config(root, config):
    path = Path(root)/'portable_runtime.py'
    if not path.is_file():
        raise ValueError('Missing portable_runtime.py; complete package bootstrap first.')
    spec = importlib.util.spec_from_file_location('cloud_portable_runtime', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    result = module.prepare(dict(config))
    if not isinstance(result, dict):
        raise TypeError('portable_runtime.prepare(config) must return a config dict.')
    return result


def update_rows(run):
    """Only aggregate update rows, never expose raw episode/snapshot/client records."""
    rows = []
    try:
        with (Path(run)/'events.jsonl').open(encoding='utf8') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if row.get('event') == 'update':
                        rows.append({k: row[k] for k in ('time', 'completed_games', 'updates', 'loss',
                            'approx_kl', 'sampled_decisions', 'unique_optimized_decisions',
                            'sample_usage_fraction', 'elapsed_seconds') if k in row})
                except (ValueError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    return rows


def status_snapshot(run, now=None):
    run = Path(run)
    launch = read_json(run/'cloud_launch.json', {})
    status = read_json(run/'status.json', {})
    progress = read_json(run/'progress.json', {})
    alive = is_alive(launch)
    state = status.get('state', 'starting')
    if not alive and state not in TERMINAL:
        state = 'failed'
    end = (now if now is not None else time.time()) if alive else status.get('updated', launch.get('started', time.time()))
    elapsed = max(0., end-launch.get('started', end))
    base = int(launch.get('base_completed_games', 0))
    total = max(base, int(status.get('completed_games', base)))
    rows = update_rows(run)
    # Count only saved/learned training lobbies; sampling progress is separate.
    recent = [(float(launch.get('started', end)), base)] + [
        (float(r['time']), int(r['completed_games'])) for r in rows
        if 'time' in r and 'completed_games' in r]
    window_start = max(float(launch.get('started', end)), end-60.)
    anchor = max((p for p in recent if p[0] <= window_start), default=recent[0], key=lambda p: p[0])
    recent_games = max(0, total-anchor[1])
    recent_seconds = max(0., end-max(window_start, float(launch.get('started', end))))
    pending = read_json(run/'control.json', {}).get('command')
    phase = state if state in TERMINAL else (progress.get('phase') or state)
    return dict(run=str(run), state=state, process_alive=alive, phase=phase,
        phase_updated=progress.get('updated'), completed_games=total, base_completed_games=base,
        new_completed_games=total-base, elapsed_seconds=elapsed,
        average_games_per_minute=(total-base)*60/elapsed if elapsed else 0.,
        recent_games_per_minute=recent_games*60/recent_seconds if recent_seconds else 0.,
        recent_window_seconds=recent_seconds, rates_count='normal training lobbies committed at optimizer/checkpoint boundaries',
        updates=status.get('updates',0), checkpoint=status.get('checkpoint'),
        pause_requested=pending=='pause', message=status.get('message', 'Waiting for trainer status.'),
        active_lobbies=progress.get('active_lobbies'),
        sampling_completed_not_yet_learned=progress.get('valid_completed_in_batch'),
        last_status_updated=status.get('updated'))


def start(args, root=ROOT):
    root = Path(root).resolve()
    with launch_lock(root):
        for existing in runs(root):
            if is_alive(read_json(existing/'cloud_launch.json', {})):
                raise ValueError('A cloud training process is still active: '+str(existing))
        source_run = None
        resume = args.resume
        if resume:
            if resume == 'latest' or Path(resume).is_dir() or (root/'data/runs'/resume).is_dir():
                source_run = resolve_run(root, resume)
                resume = str(published_checkpoint(source_run))
            else:
                resume = str(Path(resume).expanduser().resolve())
                if not Path(resume).is_file():
                    raise ValueError('Resume checkpoint does not exist.')
        config_path = Path(args.config).resolve() if args.config else (source_run/'config.json' if source_run else root/'config/cloud.json')
        config = read_json(config_path)
        if not isinstance(config, dict):
            raise ValueError('Missing or invalid config: '+str(config_path))
        if resume:
            config['resume_from'] = resume
        for option, key in [('device','device'),('workers','workers'),('rounds','rounds'),
                ('games_per_round','games_per_round'),('eval_games','eval_games'),('learning_rate','learning_rate'),('torch_threads','torch_threads')]:
            value = getattr(args, option, None)
            if value is not None:
                config[key] = value
        config['eval_every_games'] = args.eval_every  # Default0: no evaluation, including resume.
        config = prepare_config(root, config)
        base = checkpoint_games(config['resume_from']) if config.get('resume_from') else 0
        run = root/'data/runs'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        run.mkdir(parents=True)
        atomic_json(run/'config.json', config)
        atomic_json(run/'cloud_launch.json', dict(started=time.time(),base_completed_games=base,
            source_run=str(source_run) if source_run else None, pid=None,identity=None))
        env = dict(os.environ, PYTHONPATH=str(root/'app') + (os.pathsep+os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else ''),
            PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        command = [sys.executable,'-B','-m','bgagent10.training','--config',str(run/'config.json'),'--run-dir',str(run)]
        try:
            with (run/'process.log').open('ab', buffering=0) as log:
                child = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
            launch = read_json(run/'cloud_launch.json')
            launch.update(pid=child.pid, identity=process_identity(child.pid),command=command)
            atomic_json(run/'cloud_launch.json', launch)
            if not launch['identity']:
                # Child may have exited immediately; retain actual process.log and failure.
                atomic_json(run/'status.json', dict(state='failed',updated=time.time(),
                    completed_games=base,message='Trainer exited before /proc identity could be captured; inspect process.log.'))
        except Exception as error:
            atomic_json(run/'status.json',dict(state='failed',updated=time.time(),completed_games=base,message=str(error)))
            raise
        return status_snapshot(run)


def pause(run, wait_seconds=0, root=ROOT):
    with launch_lock(root):
        snapshot = status_snapshot(run)
        if snapshot['process_alive'] and snapshot['state'] not in TERMINAL:
            atomic_json(Path(run)/'control.json', {'command':'pause'})
        elif snapshot['state'] not in TERMINAL:
            raise ValueError('No active trainer to pause.')
    deadline = time.monotonic()+wait_seconds
    while wait_seconds and time.monotonic()<deadline:
        snapshot = status_snapshot(run)
        if not snapshot['process_alive'] and snapshot['state'] in TERMINAL:
            break
        time.sleep(min(.5, max(0,deadline-time.monotonic())))
    snapshot = status_snapshot(run)
    snapshot['pause_wait_complete'] = snapshot['state'] in TERMINAL and not snapshot['process_alive']
    return snapshot


def export_run(run, destination):
    run = Path(run)
    checkpoint = published_checkpoint(run)
    config = read_json(run/'config.json')
    if not isinstance(config,dict):
        raise ValueError('Run config unavailable.')
    destination = Path(destination).expanduser().resolve()
    if destination.suffix.lower() != '.zip':
        raise ValueError('Export filename must end with .zip.')
    if destination.exists():
        raise ValueError('Export already exists; choose a new filename.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp = destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
    hashes = {}
    snapshot = status_snapshot(run)
    # Snapshot the published file via one open handle: Linux rename during atomic
    # re-save cannot change this inode/stream. Never follow an unpublished temp .pt.
    try:
        with checkpoint.open('rb') as source, zipfile.ZipFile(temp,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
            digest=hashlib.sha256()
            with archive.open('checkpoint.pt','w',force_zip64=True) as target:
                while True:
                    block=source.read(1024*1024)
                    if not block:break
                    digest.update(block);target.write(block)
            hashes['checkpoint.pt']=digest.hexdigest()
            def add_json(name,value):
                content=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
                archive.writestr(name,content);hashes[name]=hashlib.sha256(content).hexdigest()
            add_json('config.json',config)
            add_json('reports/runtime_portability.json',read_json(ROOT/'build/runtime.json'))
            add_json('reports/source_hashes.json',read_json(ROOT/'SOURCE_SHA256.json'))
            add_json('reports/release_source.json',read_json(ROOT/'RELEASE_SOURCE.json'))
            add_json('reports/progress.json',snapshot)
            add_json('reports/updates.json',update_rows(run))
            error_names=sorted(str(p.relative_to(run)).replace('\\','/') for p in (run/'errors').rglob('*') if p.is_file())
            add_json('reports/errors_summary.json',dict(file_count=len(error_names),relative_filenames=error_names,
                detail_files_exported=False,note='Detailed errors, episode logs and private snapshots remain on the cloud host.'))
            manifest=dict(format='bgagent10-cloud-export-v1',created=time.time(),checkpoint='checkpoint.pt',
                checkpoint_sha256=hashes['checkpoint.pt'],config='config.json',source_run=run.name,
                published_checkpoint_name=checkpoint.name,training_only=True,
                contains_private_snapshots=False,contains_client_logs=False,contains_raw_episode_logs=False,
                error_files_retained_on_host=len(error_names),
                model_compatibility='Exact runtime binding/catalog/model contract required. No automatic cross-platform import or relabeling.',
                import_requires_portable_runtime=True,files_sha256=dict(hashes))
            add_json('export_manifest.json',manifest)
            archive.writestr('SHA256SUMS',''.join(f'{value}  {name}\n' for name,value in sorted(hashes.items())))
        os.replace(temp,destination)
    finally:
        temp.unlink(missing_ok=True)
    return dict(export=str(destination),checkpoint_sha256=hashes['checkpoint.pt'],files=len(hashes)+1,
                published_checkpoint=str(checkpoint),raw_logs_included=False)


def positive(value):
    result=int(value)
    if result<1:raise argparse.ArgumentTypeError('must be a positive integer')
    return result


def nonnegative(value):
    result=int(value)
    if result<0:raise argparse.ArgumentTypeError('must be nonnegative')
    return result


def positive_rate(value):
    result=float(value)
    if not math.isfinite(result) or result<=0:
        raise argparse.ArgumentTypeError('must be a finite positive rate')
    return result


def parser():
    cli=argparse.ArgumentParser(description=__doc__)
    commands=cli.add_subparsers(dest='command',required=True)
    launch=commands.add_parser('start')
    launch.add_argument('--config')
    launch.add_argument('--resume',nargs='?',const='latest')
    launch.add_argument('--device',choices=('cpu','cuda'))
    for name in ('workers','games-per-round','eval-games','torch-threads'):
        launch.add_argument('--'+name,type=positive)
    launch.add_argument('--rounds',type=nonnegative,help='0 means continuous until pause/stop or protective pause')
    launch.add_argument('--eval-every',type=nonnegative,default=0)
    launch.add_argument('--learning-rate',type=positive_rate)
    status=commands.add_parser('status');status.add_argument('--run',default='latest')
    status.add_argument('--watch',type=positive,metavar='SECONDS')
    stop=commands.add_parser('pause');stop.add_argument('--run',default='latest')
    stop.add_argument('--wait',type=nonnegative,default=0,metavar='SECONDS')
    export=commands.add_parser('export');export.add_argument('--run',default='latest')
    export.add_argument('--output',required=True)
    return cli


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=='start':value=start(args)
        else:
            run=resolve_run(ROOT,args.run)
            if args.command=='pause':value=pause(run,args.wait)
            elif args.command=='export':value=export_run(run,args.output)
            else:
                while True:
                    value=status_snapshot(run)
                    print(json.dumps(value,ensure_ascii=False),flush=True)
                    if not args.watch or (value['state'] in TERMINAL and not value['process_alive']):return 0
                    time.sleep(args.watch)
        print(json.dumps(value,ensure_ascii=False),flush=True)
        return 0
    except (OSError,ValueError,RuntimeError,TypeError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
