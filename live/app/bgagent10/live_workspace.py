"""Write boundary and immutable local model copies for the isolated live app."""
from pathlib import Path
import hashlib,json,os,time,uuid
from .service import atomic_json

PROJECT=Path(__file__).resolve().parents[2]
SAFE_SETTINGS={'checkpoint','window_title','client_path','log_path','auto_queue','max_games'}

def settings(saved):return {k:v for k,v in saved.items() if k in SAFE_SETTINGS}

def bounded_config(raw,project=PROJECT):
    project=Path(project).resolve();config=settings(raw)
    session=Path(raw.get('session_root',project/'data/live-sessions'/str(time.time_ns()))).resolve()
    if not session.is_relative_to(project/'data/live-sessions'):raise ValueError('实战会话必须保存在独立测试目录')
    local=project/'data/live-config'
    config.update(session_root=str(session),data_root=str(project/'data/live-data'),
        emergency_stop_path=str(session/'EMERGENCY_STOP'),device='cpu',layout_mode='log',lobby_race_source='client',
        expected_build='37.0.0.255790',client_target='37.0.0.255790',model_rules_target='37.0.0.255130',
        adapter_manifest=str(local/'adapter.json'),calibration_path=str(local/'calibration.json'),
        release_path=str(local/'release.json'),deployment_contract_path=str(local/'deployment.json'),
        software_release_path=str(project/'control/LIVE_SOFTWARE_RELEASE.json'),
        queue_timeout=180,turn_wait_seconds=180,follow_current_client_log=True,
        client_lease_path=str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'BGagent10/client-control.lock'))
    return config

def snapshot_model(path,project=PROJECT):
    source=Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower()!='.pt':raise ValueError('请选择已保存的 .pt 模型检查点')
    project=Path(project).resolve();folder=project/'runtime/models';folder.mkdir(parents=True,exist_ok=True)
    temp=folder/(uuid.uuid4().hex+'.tmp');digest=hashlib.sha256()
    before=source.stat()
    try:
        with source.open('rb') as src,temp.open('xb') as dst:
            while chunk:=src.read(1024*1024):dst.write(chunk);digest.update(chunk)
            dst.flush();os.fsync(dst.fileno())
        after=source.stat()
        if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('模型正在保存，请稍后选择已完成的检查点')
        sha=digest.hexdigest();target=folder/(sha+'.pt')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('独立模型副本校验失败')
        else:os.replace(temp,target)
        record=folder/(sha+'.json')
        if not record.exists():atomic_json(record,{'source':str(source),'sha256':sha,'snapshot':str(target),'copied_at':time.time(),'source_written':False})
        return str(target)
    finally:temp.unlink(missing_ok=True)
