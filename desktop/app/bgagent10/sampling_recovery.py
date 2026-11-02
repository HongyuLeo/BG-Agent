"""Fill a batch with normal complete lobbies, isolating failed attempts."""
import time
from .atomic_io import atomic_json, progress_json


def collect_valid(collector,model,n,config,counters,run_dir,*,evaluation=False,
                  append_event,save_boundary,read_command,set_status):
    valid=[];failures=[];consecutive=0
    field='eval_attempted_games' if evaluation else 'attempted_games'
    phase='evaluation' if evaluation else 'sampling'

    def discard(reason):
        if valid:
            append_event(dict(event='unlearned_valid_lobbies_discarded',phase=phase,reason=reason,
                              seeds=[g['seed'] for g in valid],count=len(valid)))

    while len(valid)<n:
        command=read_command()
        if command in ('pause','stop'):
            discard('user_'+command);save_boundary()
            set_status('paused' if command=='pause' else 'stopped','已按用户请求保存；未继续补采样')
            return None,failures
        count=min(n-len(valid),config['workers'])
        seed=config['seed']+(2**40 if evaluation else 0)+counters.get(field,0)
        counters[field]=counters.get(field,0)+count
        games,bad=collector.collect(model,list(range(seed,seed+count)),evaluation=evaluation,error_dir=run_dir/'errors',
            progress=lambda detail:progress_json(run_dir/'progress.json',dict(phase=phase,updated=time.time(),replacement_valid_collected=len(valid),**detail)))
        if len(games)+len(bad)!=count:raise RuntimeError('采样尝试数不守恒；未自动继续')
        valid.extend(games);failures.extend(bad);counters['quarantined']+=bad
        append_event(dict(event='sampling_lobbies',phase=phase,
            lobbies=[{k:g[k] for k in ('seed','episode_id','terminal_reason','ranks','decisions','learner_seat','learner_version','opponent_pool_hash','assignments') if k in g} for g in games]))
        if bad:
            consecutive=0 if games else consecutive+len(bad)
            counters['isolated_error_lobbies']=counters.get('isolated_error_lobbies',0)+len(bad)
            report=dict(event='quarantined',phase=phase,games=len(bad),details=bad,
                        failed_data_used_for_learning=False,consecutive_without_valid_game=consecutive)
            append_event(report)
            atomic_json(run_dir/'errors'/f'{phase}-isolation-{seed}.json',report)
            save_boundary()
            command=read_command()
            if command in ('pause','stop'):
                discard('user_'+command)
                set_status('paused' if command=='pause' else 'stopped','错误已记录，并按用户请求停止补采样')
                return None,failures
            if not config['continue_on_episode_error'] or consecutive>=config['max_consecutive_failed_lobbies']:
                discard('recovery_limit')
                set_status('paused','异常整局已隔离；'+('连续失败达到保护上限，已保存检查点' if config['continue_on_episode_error'] else '未启用单局报错继续'))
                return None,failures
            append_event(dict(event='episode_error_continued',phase=phase,failed_seeds=[x['seed'] for x in bad],valid_games_collected=len(valid),required_valid_games=n))
            set_status('evaluating' if evaluation else 'running',f'已隔离 {len(bad)} 局错误并保存报告，正在补齐有效对局')
        else:consecutive=0
    return valid,failures
