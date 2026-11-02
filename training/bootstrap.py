"""Build the bundled rules and initialize a new, untrained local model."""
import argparse, os, platform, re, subprocess, sys
from pathlib import Path
from portable_runtime import ROOT, verify_assets, read, write, sha, metadata

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu-test', action='store_true', help='CPU is already the safe default')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('Requires Linux x86_64 (including WSL2)')
    verify_assets()
    import torch
    if torch.__version__.split('+')[0] != '2.8.0': raise ValueError('Requires PyTorch 2.8.0')
    wheels = ROOT/'build/wheels'; wheels.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['PATH'] = str(Path.home()/'.cargo/bin')+os.pathsep+env.get('PATH', '')
    env['RUSTUP_TOOLCHAIN'] = '1.98.1'; env['CARGO_BUILD_JOBS'] = '2'
    # Keep compilation products out of the immutable rules sources.
    env['CARGO_TARGET_DIR'] = str(ROOT/'build/cargo-target')
    subprocess.run([sys.executable, '-m', 'maturin', 'build', '--release', '--locked', '--interpreter', sys.executable, '--out', str(wheels)], cwd=ROOT/'rules/source', env=env, check=True)
    wheel = max(wheels.glob('*.whl'), key=lambda p:p.stat().st_mtime)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--upgrade', '--target', str(ROOT/'rules/runtime'), str(wheel)], check=True)
    extensions = list((ROOT/'rules/runtime/taverngym').glob('_core*.so'))
    if len(extensions) != 1: raise ValueError('Expected exactly one native extension')
    extension = extensions[0]
    backend = (ROOT/'rules/bridge/backend.py').read_text('utf-8')
    backend, count = re.subn("PYD_SHA='[^']+'", "PYD_SHA='"+sha(extension)+"'", backend, count=1)
    if count != 1: raise ValueError('Unexpected backend binding template')
    (ROOT/'rules/bridge/backend.py').write_text(backend, encoding='utf-8', newline='\n')
    write(ROOT/'rules/bridge/BUILD_DEPENDENCY.json', dict(python=str(Path(sys.executable).absolute()), package='../runtime/taverngym/__init__.py', extension='../runtime/taverngym/'+extension.name, extension_SHA256=sha(extension)))
    meta = metadata()
    write(ROOT/'build/runtime.json', dict(binding=meta['binding'], torch=torch.__version__, wheel_sha256=sha(wheel), native_source_hash=meta['binding']['source_hash'], random_initialization_only=True))
    from bgagent10.training import validate_config, checkpoint
    from bgagent10.encoding import CardCatalog
    from bgagent10.model import PolicyModel, load_policy
    import random
    cfg = validate_config(read(ROOT/'config/cloud.json') | dict(rules_path=str(ROOT/'rules')))
    path = ROOT/'models/scratch-initial.pt'
    if path.exists():
        saved = torch.load(path, map_location='cpu', weights_only=False)
        if saved['config']['model_preset'] != cfg['model_preset'] or saved['config']['seed'] != cfg['seed']:
            raise ValueError('Existing scratch seed/preset differs; choose a clean checkout for a new experiment')
        load_policy(path, rules_path=ROOT/'rules')
    else:
        torch.set_num_threads(cfg['torch_threads']); random.seed(cfg['seed']); torch.manual_seed(cfg['seed'])
        catalog = CardCatalog(ROOT/'rules'); model = PolicyModel(catalog, meta['layout'], cfg['model_preset'])
        optimizer = torch.optim.AdamW(model.parameters(), lr=cfg['learning_rate'])
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _:1.)
        path.parent.mkdir(parents=True, exist_ok=True)
        counters = dict(completed_games=0, attempted_games=0, eval_attempted_games=0, round=0, updates=0, quarantined=[])
        checkpoint(path, model, optimizer, scheduler, cfg, catalog, meta['binding'], counters, None)
        load_policy(path, rules_path=ROOT/'rules')
    write(ROOT/'READY.json', dict(ready=True, checkpoint='models/scratch-initial.pt', checkpoint_sha256=sha(path), training_started=False, random_initialization_only=True))
    print('READY: locally initialized untrained model; no training started.')
if __name__ == '__main__': main()
