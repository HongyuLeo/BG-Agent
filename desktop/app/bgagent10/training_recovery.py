"""Apply a published, exact checkpoint recovery without relaxing model checks.

This only routes already audited immutable artifacts. It never migrates an
arbitrary checkpoint, edits an old run, starts a process, or discards an error.
"""
import copy
import hashlib
import json
from pathlib import Path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_file(path, expected):
    path = Path(path).resolve()
    if not path.is_file() or _sha(path) != expected:
        raise ValueError('训练修复文件校验失败，请保留现场：' + str(path))
    return path


def prepare_config(config, project=None):
    """Return a new config and audit receipt; leave the supplied config intact."""
    project = Path(project or Path(__file__).resolve().parents[2]).resolve()
    registry_path = project / 'control/TRAINING_RULE_RECOVERY.json'
    result = copy.deepcopy(config)
    if not registry_path.exists():
        return result, None
    registry_bytes = registry_path.read_bytes()
    registry_sha = hashlib.sha256(registry_bytes).hexdigest()
    registry = json.loads(registry_bytes)
    if registry.get('schema') != 'bgagent10-exact-rule-recovery-v1' or registry.get('status') != 'approved':
        raise ValueError('训练规则修复尚未完成审查，请暂勿续训')
    old_rules = Path(registry['old_rules_path']).resolve()
    new_rules = Path(registry['new_rules_path']).resolve()
    additional = registry.get('additional_old_rules_paths', [])
    if not isinstance(additional, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in additional):
        raise ValueError('训练修复旧版本路径清单无效')
    old_rules_set = {old_rules, *(Path(p).resolve() for p in additional)}
    if new_rules in old_rules_set:
        raise ValueError('训练修复新旧版本路径重复')
    requested = Path(result.get('rules_path') or old_rules).resolve()
    if requested not in old_rules_set and requested != new_rules:
        raise ValueError('指定规则不属于当前已审查版本，未自动替换')
    for rel, expected in registry['candidate_files'].items():
        path = (new_rules / rel).resolve()
        if not path.is_relative_to(new_rules):
            raise ValueError('训练修复清单路径越界')
        _check_file(path, expected)
    _check_file(registry['acceptance']['path'], registry['acceptance']['sha256'])
    replacements = registry['checkpoint_replacements']
    used = []

    def replacement(path, *, required, expected_sha=None):
        source = Path(path).resolve()
        source_sha = _sha(source)
        if expected_sha is not None and source_sha != expected_sha:
            raise ValueError('固定对手原文件校验失败，未替换：' + str(source))
        for entry in replacements:
            if source_sha == entry['source_sha256']:
                destination = _check_file(entry['destination'], entry['destination_sha256'])
                _check_file(entry['verification']['path'], entry['verification']['sha256'])
                used.append({'source': str(source), 'source_sha256': source_sha,
                             'destination': str(destination),
                             'destination_sha256': entry['destination_sha256']})
                return str(destination), entry['destination_sha256']
            if source == Path(entry['destination']).resolve():
                _check_file(source, entry['destination_sha256'])
                _check_file(entry['verification']['path'], entry['verification']['sha256'])
                return str(source), source_sha
        if required:
            raise ValueError('这个旧检查点尚未完成规则修复兼容核验。请在当前运行中选择 '
                             + registry['recommended_run'] + '，使用其最新检查点续训。')
        # Newly saved checkpoints still undergo the trainer/FrozenPool's exact
        # binding, catalog and learning-contract checks; none are waived here.
        return str(source), source_sha

    if result.get('resume_from'):
        result['resume_from'], _ = replacement(result['resume_from'], required=requested in old_rules_set)
    for field in ('train_opponent_pool', 'eval_opponent_pool'):
        spec = result.get(field)
        if spec is None:
            continue
        if isinstance(spec, str):
            source = Path(spec).resolve()
            value = json.loads(source.read_text('utf-8-sig'))
            entries = value['opponents'] if isinstance(value, dict) else value
            entries = copy.deepcopy(entries)
            for entry in entries:
                if entry.get('kind') == 'checkpoint':
                    entry['path'] = str((source.parent / entry['path']).resolve())
        elif isinstance(spec, list):
            entries = copy.deepcopy(spec)
        else:
            raise ValueError('固定对手配置格式错误')
        for entry in entries:
            if entry.get('kind') == 'checkpoint':
                if not entry.get('sha256'):
                    raise ValueError('固定对手必须保留已固定的 SHA256')
                entry['path'], entry['sha256'] = replacement(entry['path'],
                    required=requested in old_rules_set, expected_sha=entry['sha256'])
        result[field] = entries
    result['rules_path'] = str(new_rules)
    if _sha(registry_path) != registry_sha:
        raise ValueError('训练修复注册表在检查期间变化，请重新打开软件后再操作')
    receipt = {'repair_id': registry['repair_id'], 'registry': str(registry_path),
               'registry_sha256': registry_sha, 'old_rules_path': str(old_rules),
               'new_rules_path': str(new_rules), 'replacements': used,
               'originals_modified': False, 'optimizer_reset_for_migrated_checkpoints': True,
               'evaluation_invalidated_for_migrated_checkpoints': True}
    return result, receipt
