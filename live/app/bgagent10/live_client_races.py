"""Read only the client's public lobby tribe enumeration, never shop inference.

The helper has no input/write privileges. A cache lives only in this object;
disk records are audit evidence and are never trusted to bind a later game.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from .live_data import atomic, immutable
from .live_native import InputStopped
from .live_encoding import RACES

RACE_IDS={20:'BEAST',15:'DEMON',24:'DRAGON',18:'ELEMENTAL',17:'MECHANICAL',14:'MURLOC',23:'PIRATE',43:'QUILBOAR',11:'UNDEAD',126:'ABERRATION',92:'NAGA'}
FIELD='GameState.s_instance.m_availableRacesInBattlegroundsExcludingAmalgam'
DOTNET_FILETIME_OFFSET=504911232000000000

class PublicRacesPending(RuntimeError):pass

def check_stop(config,stop):
    emergency=config.get('emergency_stop_path')
    control=Path(config['session_root'])/'control.json'
    if stop.is_set() or (emergency and Path(emergency).exists()):raise InputStopped('读取公开种族时已紧停')
    if control.exists() and json.loads(control.read_text('utf8')).get('command')=='stop':raise InputStopped('读取公开种族时已停止')

def run_helper(args,config,stop,timeout=5):
    """Poll so a stop cancels the read-only child, without touching the game."""
    check_stop(config,stop)
    child=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    deadline=time.monotonic()+timeout
    try:
        while True:
            check_stop(config,stop)
            try:out,err=child.communicate(timeout=.05);break
            except subprocess.TimeoutExpired:
                if time.monotonic()>=deadline:raise TimeoutError('读取客户端公开种族超时')
        if len(out)>65536:raise ValueError('公开种族助手响应过大')
        try:result=json.loads(out.decode('utf-8-sig'))
        except (ValueError,UnicodeError) as exc:raise ValueError('公开种族助手未返回有效结果') from exc
        if child.returncode or result.get('ok') is not True:
            error=PublicRacesPending if result.get('retryable') is True else ValueError
            raise error('客户端种族读取失败：'+str(result.get('error','未知读取错误'))[:600])
        return result
    finally:
        if child.poll() is None:child.kill()
        child.communicate()

def network_connection(path):
    connection=None
    with Path(path).with_name('GameNetLogger.log').open('r',encoding='utf8',errors='replace') as stream:
        for line in stream:
            if 'Network.GotoGameServe()' in line:
                match=re.search(r'\bgame=(\d+),\s*client=(\d+)',line)
                if match:
                    stamp=re.match(r'[A-Z] (\d\d):(\d\d):(\d\d)(?:\.(\d+))?',line)
                    if not stamp:raise ValueError('当前连接日志时间格式不支持')
                    connection={'game':int(match[1]),'client':int(match[2]),
                        'clock_seconds':int(stamp[1])*3600+int(stamp[2])*60+int(stamp[3])+float('0.'+(stamp[4] or '0'))}
    if not connection:raise ValueError('当前会话缺少公开连接标识，不能绑定种族名单')
    return connection

def log_binding(path,game_key,created):
    """Bind the latest CREATE and public network connection, excluding secrets."""
    path=Path(path).resolve();stat=path.stat()
    if stat.st_size>256*1024*1024:raise ValueError('日志过大，需重新建立当前会话')
    if stat.st_mtime+2 < int(created)/10000000-11644473600:raise ValueError('日志早于当前客户端进程')
    create=None;offset=0
    with path.open('rb') as stream:
        for raw in stream:
            if b'GameState.DebugPrintPower()' in raw and b'CREATE_GAME' in raw:
                stamp=re.match(rb'[A-Z] (\d\d):(\d\d):(\d\d)(?:\.(\d+))?',raw)
                if not stamp:raise ValueError('当前对局日志时间格式不支持')
                create={'path':str(path),'offset':offset,'sha256':hashlib.sha256(raw).hexdigest(),
                    'clock_seconds':int(stamp[1])*3600+int(stamp[2])*60+int(stamp[3])+float('0.'+(stamp[4] or b'0').decode())}
            offset+=len(raw)
    if not create:raise ValueError('日志中没有当前对局起点')
    key=hashlib.sha256((create['path']+':'+str(create['offset'])+':'+create['sha256']).encode()).hexdigest()
    if key!=game_key:raise ValueError('读取种族期间日志已进入另一局，请重新读取当前局')
    # Capture only non-secret numeric session identities. Never persist a raw
    # network log line (which may also carry authentication/spectator tokens).
    connection=network_connection(path)
    # A new connection may already exist before its CREATE reaches Power.log.
    # Never associate the previous CREATE with that new in-memory lobby.
    delay=(create['clock_seconds']-connection['clock_seconds'])%86400
    if delay>180:raise ValueError('对局起点不属于最近连接，等待当前局日志')
    return {'game_key':key,'create':create,'file_identity':[stat.st_dev,stat.st_ino],'connection':connection}

class PublicClientRaceReader:
    def __init__(self,root,*,backend=run_helper,identity=None,binder=log_binding,helper=None,connection_reader=network_connection):
        from .service import process_identity
        self.root=Path(root);self.backend=backend;self.identity=identity or process_identity;self.binder=binder
        self.helper=Path(helper) if helper else Path(__file__).with_name('public_races')/'PublicRaces.exe'
        self.active=None;self.connection_reader=connection_reader

    def observe(self,report,window,config,stop):
        check_stop(config,stop)
        key=report.get('game_key');pid=window['pid'];created=self.identity(pid)
        if not key or report.get('terminal') or not created:raise ValueError('公开种族必须绑定当前存活客户端及未结束的对局')
        expected=config.get('client_target','37.0.0.255790');build=int(expected.rsplit('.',1)[-1])
        if expected!='37.0.0.255790' or report.get('build_numbers')!=[build]:raise ValueError('种族读取仅适配客户端/日志255790，版本不符')
        if Path(window['exe']).resolve()!=Path(config['client_path']).resolve():raise ValueError('种族读取窗口进程路径不符')
        cache_key=(key,pid,created)
        if self.active and self.active[0]==cache_key:
            record=self.active[1]
            saved=next(iter(record['lobby_races'].values()))['source']['binding']
            if self.connection_reader(config['log_path'])!=saved['connection']:
                self.active=None
                error={'known':False,'game_key':key,'reason':'客户端连接已变化，等待本局日志，禁止复用旧种族'}
                atomic(self.root/'active.json',error)
                raise ValueError(error['reason'])
            return record
        before=self.binder(config['log_path'],key,created)
        args=[str(self.helper),'--pid',str(pid),'--expected-exe',str(Path(config['client_path']).resolve()),
            '--expected-build',str(build),'--expected-start-ticks',str(int(created)+DOTNET_FILETIME_OFFSET)]
        attempt=self.root/'attempts'/uuid.uuid4().hex
        try:
            deadline=time.monotonic()+15
            while True:
                try:result=self.backend(args,config,stop);break
                except PublicRacesPending:
                    check_stop(config,stop)
                    if time.monotonic()>=deadline:raise
                    stop.wait(.2)
            check_stop(config,stop)
            after=self.binder(config['log_path'],key,created)
            if before!=after or self.identity(pid)!=created:raise ValueError('读取期间对局或客户端已变化，结果已丢弃')
            if (result.get('pid')!=pid or str(result.get('process_start_ticks'))!=str(int(created)+DOTNET_FILETIME_OFFSET)
                or str(result.get('client_build'))!=str(build) or result.get('source_field')!=FIELD):raise ValueError('客户端种族返回的进程、版本或来源不符')
            if not result.get('game_state_id') or not result.get('game_entity_id') or result.get('game_over') is not False:raise ValueError('客户端尚未提供当前未结束对局')
            if (result.get('network_game_id')!=before['connection']['game'] or result.get('network_client_id')!=before['connection']['client']):raise ValueError('客户端与日志不是同一场对局，种族结果已丢弃')
            ids=result.get('race_ids')
            if not isinstance(ids,list) or not 1<=len(ids)<=len(RACES) or any(type(i) is not int or i not in RACE_IDS for i in ids) or len(set(ids))!=len(ids):raise ValueError('客户端种族名单为空、重复或包含未适配种族')
            proof={'kind':'local_public_client_field','game_key':key,'pid':pid,'process_created':created,
                'client_build':expected,'log_build':build,'source_field':FIELD,'binding':before,
                'game_state_id':result['game_state_id'],'game_entity_id':result['game_entity_id'],
                'observed_at':time.time(),'helper_sha256':hashlib.sha256(self.helper.read_bytes()).hexdigest()}
            immutable(attempt/'read.json',result)
            evidence={'path':str((attempt/'read.json').resolve()),'sha256':hashlib.sha256((attempt/'read.json').read_bytes()).hexdigest()}
            proof['evidence']=evidence
            enabled={RACE_IDS[i] for i in ids}
            record={'known':True,'game_key':key,'lobby_races':{race:{'known':True,'value':int(race in enabled),'source':proof,'basis':'complete public client enumeration; no shop inference'} for race in RACES},'evidence':evidence}
            immutable(attempt/'RESULT.json',record);atomic(self.root/'active.json',record)
            self.active=(cache_key,record);return record
        except InputStopped:raise
        except Exception as exc:
            record={'known':False,'game_key':key,'reason':str(exc),'method':'public_client_readonly'}
            immutable(attempt/'ERROR.json',record);atomic(self.root/'active.json',record)
            raise ValueError('无法读取本局公开种族：'+str(exc)+'；读取报告：'+str(attempt/'ERROR.json')) from exc
