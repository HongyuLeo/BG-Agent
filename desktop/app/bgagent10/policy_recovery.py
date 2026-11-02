"""Route only owner-reviewed policy recovery copies; never mutate checkpoints."""
import copy
import hashlib
import json
from pathlib import Path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _verify(item):
    path = Path(item['path']).resolve()
    if not path.is_file() or _sha(path) != item['sha256']:
        raise ValueError('模型修复文件校验失败：' + str(path))
    return path


def prepare_policy_config(config, project=None):
    project = Path(project or Path(__file__).resolve().parents[2]).resolve()
    path = project / 'control/POLICY_RECOVERY.json'
    result = copy.deepcopy(config)
    if not path.exists():
        return result, None
    registry_hash = _sha(path)
    registry = json.loads(path.read_text('utf-8-sig'))
    if registry.get('schema') != 'bgagent10-policy-recovery-v1' or registry.get('status') != 'approved':
        raise ValueError('模型修复尚未完成审查')
    for relative, expected in registry['app_files'].items():
        candidate = (project / relative).resolve()
        if not candidate.is_relative_to(project / 'app'):
            raise ValueError('模型修复文件路径越界')
        _verify({'path': str(candidate), 'sha256': expected})
    _verify(registry['acceptance'])
    replacement = None
    if result.get('resume_from'):
        source = Path(result['resume_from']).resolve()
        source_hash = _sha(source)
        for entry in registry['replacements']:
            if source_hash == entry['source']['sha256']:
                destination = _verify(entry['destination'])
                _verify(entry['verification'])
                result['resume_from'] = str(destination)
                replacement = {'source': str(source), 'source_sha256': source_hash,
                               'destination': str(destination), 'destination_sha256': entry['destination']['sha256']}
                break
        # Other saved checkpoints still pass the trainer's full current-contract,
        # rules, catalog and model-state checks. No automatic arbitrary migration.
    if _sha(path) != registry_hash:
        raise ValueError('模型修复注册表在检查期间变化，请重新打开软件')
    return result, {'repair_id': registry['repair_id'], 'registry_sha256': registry_hash,
                    'replacement': replacement, 'old_files_modified': False,
                    'old_policy_preserved_for_fixed_opponents': True}
