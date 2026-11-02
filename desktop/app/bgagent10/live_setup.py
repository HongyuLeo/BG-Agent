"""Bind any compatible local trained model to reviewed software, without JSON editing."""
from pathlib import Path
import hashlib
import json

from .live_data import digest
from .service import atomic_json

PROJECT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def prepare_model(config):
    """No client input. Software approval covers code; model approval is compatibility.

    A new compatible checkpoint needs no human-authored release file. It still
    passes the same strict load_policy rules/catalog/learning-contract checks.
    Nothing here grants permission to skip live observation or window checks.
    """
    config = dict(config)
    software_path = Path(config.get('software_release_path', PROJECT / 'control/LIVE_SOFTWARE_RELEASE.json'))
    if not software_path.is_file():
        raise ValueError('实战组件仍在整合，软件验证记录尚未就绪。无需手工编写配置文件。')
    software = read(software_path)
    review_states = {'passed', 'ready_for_user_acceptance'}
    if software.get('format') != 'bgagent10-live-software-v1' or software.get('state') not in review_states:
        raise ValueError('实战软件验证尚未通过')
    if software.get('state') == 'ready_for_user_acceptance' and software.get('runtime_observation_must_be_complete') is not True:
        raise ValueError('手动验收版本缺少逐步完整观察保护')
    for key, expected in [('model_rules_target', '37.0.0.255130'), ('client_target', '37.0.0.255790')]:
        if software.get(key) != expected or config.get(key, expected) != expected:
            raise ValueError('软件和所选客户端目标不一致：' + key)
    manifest = software.get('source_manifest', {})
    if not manifest:
        raise ValueError('软件验证记录缺少文件校验')
    for relative, expected in manifest.items():
        path = (PROJECT / relative).resolve()
        if not path.is_relative_to(PROJECT) or sha(path) != expected:
            raise ValueError('实战软件文件与已验证版本不一致：' + relative)
    mapping = Path(software['mapping_validation_path'])
    if sha(mapping) != software.get('mapping_validation_sha256'):
        raise ValueError('公开状态映射验证记录已变化')
    report = read(mapping)
    if (report.get('state') not in review_states or report.get('unresolved_required_fields')
            or not report.get('validated_phases')
            or report.get('model_rules_target') != software['model_rules_target']
            or report.get('client_target') != software['client_target']):
        raise ValueError('公开状态映射验证范围尚未就绪')
    checkpoint = Path(config.get('checkpoint', '')).resolve()
    if not checkpoint.is_file():
        raise ValueError('请选择已保存的训练模型')
    model_sha = sha(checkpoint)
    from .model import load_policy
    import torch
    model = load_policy(checkpoint, 'cpu', config.get('rules_path'))
    if any(not torch.isfinite(value).all().item() for value in model.state_dict().values() if value.is_floating_point()):
        raise ValueError('模型含无效数值，请选择正常保存的检查点')
    saved = torch.load(checkpoint, map_location='cpu', weights_only=False)
    if sha(checkpoint) != model_sha:
        raise ValueError('检查期间模型文件变化，请选择已完成保存的检查点')
    contract = saved['contract']
    versions = dict(engine_hash=digest(saved['binding']),
        rules_manifest_hash=saved['binding']['named_target_roster_binding_SHA'],
        observation_schema=contract['observation'], action_schema=contract['action'],
        card_mapping_hash=saved['catalog']['mapping_hash'], reward_version=contract['reward'],
        policy_version=model_sha, software_version=sha(software_path),
        model_rules_target='37.0.0.255130', authorized_client_target='37.0.0.255790')
    folder = Path(config['session_root']) / 'model-binding'
    release = folder / ('model-' + model_sha[:16] + '.json')
    deployment = folder / ('deployment-' + model_sha[:16] + '.json')
    atomic_json(release, dict(live_released=True, checkpoint_sha256=model_sha,
        release_scope=software['state'], real_client_accepted=software['state']=='passed',
        validation='strict rules/catalog/learning-contract and finite weights',
        software_review_path=str(software_path), software_review_sha256=sha(software_path),
        note='Compatible trained checkpoints are selected by the user; no per-model manual approval is needed.'))
    atomic_json(deployment, dict(format='bgagent10-deployment-v1',
        model_rules_target='37.0.0.255130', client_target='37.0.0.255790',
        checkpoint_sha256=model_sha, mapping_validation_path=str(mapping),
        mapping_validation_sha256=sha(mapping), commander_approved=True,
        approval_basis='Inherited reviewed software mapping; selected model passed strict compatibility checks',
        software_review_path=str(software_path), software_review_sha256=sha(software_path)))
    config.update(checkpoint=str(checkpoint), release_path=str(release), deployment_contract_path=str(deployment),
        expected_versions=versions, model_rules_target='37.0.0.255130', client_target='37.0.0.255790',
        expected_build='37.0.0.255790')
    return config
