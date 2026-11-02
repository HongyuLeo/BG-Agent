"""Select one fixed isolated rule profile; never follow the parent registry."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from .live_model_info import inspect_checkpoint

PROJECT=Path(__file__).resolve().parents[2]
REQUIRED_FILES={'target37_entry.py','bridge/backend.py','bridge/BUILD_DEPENDENCY.json',
    'bridge/SOURCE_LOCK.json','bridge/SOURCE_VARIANT.json','bridge/API_CONTRACT.json','bridge/POLICY.json',
    'bridge/TARGET_CROSS_TABLE.json','runtime/taverngym/__init__.py','runtime/taverngym/_core.pyd',
    'source/crates/taverngym/data/cards.json','TARGET_ROSTER_BINDING.json'}


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _select_rules_profile(config,project=PROJECT):
    """CPU metadata/catalog validation only. Original strict load_policy follows."""
    project=Path(project).resolve();profile_path=project/'control/LIVE_RULE_PROFILES.json'
    if not profile_path.is_file():raise ValueError('实战规则兼容资料尚未就绪，无需手工选择规则路径')
    raw=profile_path.read_bytes();profile_sha=hashlib.sha256(raw).hexdigest()
    try:document=json.loads(raw.decode('utf-8-sig'))
    except (ValueError,UnicodeError) as exc:raise ValueError('实战规则兼容资料无法读取') from exc
    if document.get('format')!='bgagent10-live-rule-profiles-v1' or document.get('state') not in {'passed','ready_for_user_acceptance'}:
        raise ValueError('实战规则兼容资料尚未批准')
    info=inspect_checkpoint(config.get('checkpoint',''))
    profiles=document.get('profiles',[])
    matches=[p for p in profiles if p.get('binding')==info['binding']]
    if len(matches)!=1:raise ValueError('该模型的完整规则绑定未获实战测试批准，不能自动猜测兼容版本')
    profile=matches[0]
    if (profile.get('model_rules_target')!='37.0.0.255130' or profile.get('client_target')!='37.0.0.255790'):
        raise ValueError('规则资料的训练目标或实战客户端版本不符')
    from .model import identify_model_contract
    from .encoding import CardCatalog
    actor_version=identify_model_contract(info['contract'])
    allowed_contracts=document.get('learning_contracts')
    if allowed_contracts is None:allowed_contracts=[document.get('learning_contract')]
    if not isinstance(allowed_contracts,list) or not allowed_contracts:
        raise ValueError('规则资料缺少明确的模型学习契约')
    for contract in allowed_contracts:identify_model_contract(contract)
    if info['contract'] not in allowed_contracts:
        raise ValueError('模型学习契约不符，不能通过切换规则绕过')
    if not isinstance(info['catalog'],dict) or info['catalog']!=document.get('catalog'):
        raise ValueError('模型完整卡表或身份映射不符')
    rules=Path(profile['rules_path']).resolve();manifest=profile.get('files',{})
    if not isinstance(manifest,dict) or not REQUIRED_FILES.issubset(manifest):raise ValueError('规则文件清单缺少入口、卡表或原生模块')
    for relative,expected in manifest.items():
        path=(rules/relative).resolve()
        if not path.is_relative_to(rules):raise ValueError('规则文件清单越界')
        if not path.is_file() or _sha(path)!=expected:raise ValueError('实战规则文件已变化：'+str(relative))
    if CardCatalog(rules).manifest()!=info['catalog']:raise ValueError('所选规则的实际完整卡表与模型不符')
    if info['catalog'].get('source_sha')!=profile['binding'].get('card_table_file_SHA'):
        raise ValueError('规则绑定的卡表来源不符')
    if _sha(profile_path)!=profile_sha:raise ValueError('读取期间规则兼容资料发生变化，请重新检查')
    result=copy.deepcopy(config)
    result.update(actor_version=actor_version,rules_path=str(rules),rules_profile_id=profile['id'],rules_profile_label=profile.get('label',profile['id']),
        rules_profiles_sha256=profile_sha,rules_binding_sha256=hashlib.sha256(json.dumps(info['binding'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf8')).hexdigest())
    return result


def select_rules_profile(config,project=PROJECT):
    """Public fixed-profile selector; no backend or live client is started."""
    try:return _select_rules_profile(config,project)
    except ValueError:raise
    except Exception as exc:raise ValueError('无法选择模型规则：'+str(exc)) from exc
