"""Trusted subprocess driver: sealed interpreter, named entry, exact action tickets.

Only public numeric observations cross the policy boundary. This is an information
boundary, not a Python security sandbox. No changes to the sealed installation.
"""
import json, os, subprocess, sys, traceback
from pathlib import Path

DEFAULT_RULES = Path(os.environ.get('BGAGENT10_RULES_PATH', Path(__file__).resolve().parents[2] / 'rules'))

def public_input(obs):
    result = {k: obs[k] for k in ('features', 'cards', 'action_mask')}
    if tuple(map(len, result.values())) != (3227, 124, 245):
        raise ValueError('observation schema drift')
    return result

class EnvironmentProcess:
    def __init__(self, rules_path=DEFAULT_RULES, timeout=180):
        self.rules_path = Path(rules_path).resolve()
        dep = json.loads((self.rules_path/'bridge/BUILD_DEPENDENCY.json').read_text('utf8'))
        self.proc = subprocess.Popen([dep['python'], str(Path(__file__).resolve()), '--worker', str(self.rules_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf8', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.timeout = timeout
        # Reader thread only transports stdout. Environment itself is a separate OS process.
        import queue, threading
        self.messages = queue.Queue()
        def reader():
            for line in self.proc.stdout: self.messages.put(line)
            self.messages.put(None)
        threading.Thread(target=reader, daemon=True).start()
        try: self.metadata = self.request('metadata')
        except BaseException:
            self.close()
            raise

    def request(self, command, **kwargs):
        import queue
        self.proc.stdin.write(json.dumps(dict(command=command, **kwargs))+'\n'); self.proc.stdin.flush()
        try: line = self.messages.get(timeout=self.timeout)
        except queue.Empty:
            self.close(); raise TimeoutError('sealed environment worker timed out')
        if line is None:
            raise RuntimeError('environment worker exited: '+self.proc.stderr.read()[-4000:])
        response = json.loads(line)
        if 'error' in response: raise RuntimeError(response['error'])
        return response['result']

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait()
        for stream in (self.proc.stdin,self.proc.stdout,self.proc.stderr):
            if stream: stream.close()

def worker(rules):
    sys.path.insert(0, str(rules))
    from target37_entry import create_target37_backend
    from backend import tg, build_binding
    backend = None; trace=[]
    for line in sys.stdin:
        try:
            command = json.loads(line); kind = command['command']
            if kind == 'metadata':
                result = {'binding':build_binding(), 'layout':dict(tg.layout()),
                    'action_names':[tg.action_name(i) for i in range(245)],
                    'pid':os.getpid()}
            elif kind == 'reset':
                backend = create_target37_backend(seed=command['seed'])
                trace=[]
                result = backend.observe()
            elif kind == 'dump_debug':
                # Privileged material is written directly to trusted storage, never policy input.
                destination=Path(command['path']); destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_text(json.dumps({'snapshot':backend.snapshot() if backend else None,
                    'actions':trace,'rejections':backend.rejections if backend else [],'diagnostics':backend.observe()['diagnostics'] if backend else None}),encoding='utf8')
                result={'written':str(destination)}
            elif kind == 'step':
                if backend is None: raise ValueError('reset required')
                index = command['index']
                tickets = [a for a in backend.legal_actions() if a['index'] == index]
                if len(tickets) != 1: raise ValueError('illegal action, no fallback allowed')
                trace.append({'seat':tickets[0]['seat'],'index':index,'revision':tickets[0]['revision']})
                result = backend.step(tickets[0])
            else: raise ValueError('unknown worker command')
            print(json.dumps({'result':result}), flush=True)
        except Exception:
            print(json.dumps({'error':traceback.format_exc()}), flush=True)

if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker': raise SystemExit('private driver entry')
    worker(Path(sys.argv[2]))
