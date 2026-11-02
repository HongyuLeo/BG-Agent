#!/usr/bin/env python3
"""中文训练进度；只读本地状态，不启动或控制训练。"""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
import cloud_run

PHASES = {'starting':'正在启动', 'sampling':'采集完整训练对局', 'running':'正在训练',
          'evaluation':'正在评估', 'evaluating':'正在评估', 'paused':'已暂停',
          'stopped':'已停止', 'completed':'训练完成', 'failed':'训练异常或进程已退出'}


def duration(seconds):
    total=max(0,int(seconds or 0));hours,remainder=divmod(total,3600);minutes,secs=divmod(remainder,60)
    return f'{hours}小时{minutes:02d}分{secs:02d}秒'


def error_count(run):
    """文件数，不把一个局的多个诊断文件误报成多局失败。"""
    return sum(1 for path in (Path(run)/'errors').rglob('*') if path.is_file())


def render(snapshot, errors=0):
    phase=PHASES.get(snapshot.get('phase'),snapshot.get('phase') or '等待状态')
    state=snapshot.get('state')
    if snapshot.get('pause_requested') and state not in cloud_run.TERMINAL:
        phase+='（已请求暂停，等待安全保存）'
    checkpoint=snapshot.get('checkpoint')
    # Accept a Windows-style historical value too; monitor may inspect imported metadata.
    filename=str(checkpoint).replace('\\','/').rsplit('/',1)[-1] if checkpoint else '尚未保存'
    lines=[f"训练进度  {datetime.now().strftime('%H:%M:%S')}",
        f"本次新增：{snapshot.get('new_completed_games',0)} 局　累计：{snapshot.get('completed_games',0)} 局",
        f"平均速度：{snapshot.get('average_games_per_minute',0):.2f} 局/分钟　近期速度：{snapshot.get('recent_games_per_minute',0):.2f} 局/分钟",
        f"当前阶段：{phase}　运行时长：{duration(snapshot.get('elapsed_seconds',0))}",
        f"优化器累计更新：{snapshot.get('updates',0)} 次",f"已保存模型：{filename}",f"错误诊断文件：{errors} 个（不是失败局数；详细内容未展开）"]
    active=snapshot.get('active_lobbies')
    if snapshot.get('process_alive') and active is not None:
        lines.append(f'当前进行中的对局：{active} 局')
    pending=snapshot.get('sampling_completed_not_yet_learned')
    if snapshot.get('process_alive') and pending is not None:
        lines.append(f'本批已完成、尚未用于更新：{pending} 局')
    if snapshot.get('message'):
        lines.append('状态说明：'+str(snapshot['message']))
    if state in cloud_run.TERMINAL and snapshot.get('process_alive'):
        lines.append('正在等待训练进程完成清理。')
    lines.append('速度按已提交训练的完整对局计算，批次保存时会跳动；近期窗口最长60秒。')
    return '\n'.join(lines)


def main(argv=None, root=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',default='latest',help='训练记录名称/目录，默认最近记录')
    parser.add_argument('--once',action='store_true',help='只显示一次')
    args=parser.parse_args(argv)
    root=cloud_run.ROOT if root is None else Path(root)
    selected=None
    try:
        while True:
            try:
                if selected is None:
                    selected=cloud_run.resolve_run(root,args.run)
                if not (selected/'status.json').is_file():
                    launch=cloud_run.read_json(selected/'cloud_launch.json',{})
                    if cloud_run.is_alive(launch):
                        text='训练已启动，正在等待第一份状态记录；请稍候。'
                        finished=False
                    else:
                        text='尚未读取到训练状态，且未发现对应训练进程。请查看训练记录和 process.log。'
                        finished=True
                else:
                    snapshot=cloud_run.status_snapshot(selected)
                    text=render(snapshot,error_count(selected))
                    finished=snapshot['state'] in cloud_run.TERMINAL and not snapshot['process_alive']
            except (ValueError,OSError) as error:
                text='暂未找到可读取的训练记录。请先启动训练，或用 --run 选择已有记录。\n说明：'+str(error)
                finished=args.run!='latest'
            if sys.stdout.isatty():
                print('\033[2J\033[H',end='')
            print(text,flush=True)
            if args.once or finished:return 0
            time.sleep(5)
    except KeyboardInterrupt:
        print('\n已退出监控，训练仍按原状态运行。',flush=True)
        return 0


if __name__=='__main__':
    raise SystemExit(main())
