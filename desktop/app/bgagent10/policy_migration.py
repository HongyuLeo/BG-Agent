"""Explicit legacy -> stable actor migration. Not a strength promotion."""
import copy
import hashlib
from pathlib import Path
import torch
from .atomic_io import atomic_write
from .model import (PolicyModel, build_checkpoint_model, identify_model_contract,
                    model_contract, LEGACY_ACTOR_VERSION, STABLE_ACTOR_VERSION)


def migrate_actor_checkpoint(source, destination, catalog, metadata, *, rules_path):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists() or source == destination:
        raise ValueError('模型迁移必须保存为新文件')
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    saved = torch.load(source, map_location='cpu', weights_only=False)
    if identify_model_contract(saved.get('contract')) != LEGACY_ACTOR_VERSION:
        raise ValueError('只接受已核验的旧动作评分模型')
    old_model = build_checkpoint_model(saved, catalog, metadata, device='cpu', expected_actor=LEGACY_ACTOR_VERSION)
    with torch.random.fork_rng():
        model = PolicyModel(catalog, metadata['layout'], saved['config']['model_preset'])
    model.load_state_dict(old_model.state_dict(), strict=True)
    for key, value in saved['model'].items():
        if not torch.equal(value, model.state_dict()[key]):
            raise ValueError('迁移改变了原模型参数或缓冲区：' + key)
    candidate = copy.deepcopy(saved)
    candidate['model'] = model.state_dict()
    candidate['contract'] = model_contract()
    candidate['policy_version'] = STABLE_ACTOR_VERSION
    candidate['config']['rules_path'] = str(Path(rules_path).resolve())
    optimizer = torch.optim.AdamW(model.parameters(), lr=saved['config']['learning_rate'])
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _: 1.)
    candidate.update(optimizer=optimizer.state_dict(), scheduler=scheduler.state_dict(), scaler=None,
                     evaluation=None, last_promotion=None, anchor=None)
    candidate['normalization'] = {'type': 'native fixed scales; no running moments',
                                  'actor': STABLE_ACTOR_VERSION}
    candidate['curriculum'] = {'stage': 'actor-stability-adaptation', 'promotion_requires_independent_evaluation': True}
    candidate['policy_migration'] = {
        'kind': 'actor-stability-v2', 'source': str(source), 'source_sha256': original_hash,
        'source_contract': saved['contract'], 'destination_contract': candidate['contract'],
        'all_saved_tensors_preserved': True, 'optimizer_reset': True,
        'old_evaluation_invalidated': True, 'forward_function_changed': True,
        'old_environment_or_recurrent_state_resumed': False, 'strength_improved': False,
        'old_training_data_reused': False,
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    # Strict new loader must accept the newly declared semantics before writing.
    build_checkpoint_model(candidate, catalog, metadata, device='cpu', expected_actor=STABLE_ACTOR_VERSION)
    if hashlib.sha256(source.read_bytes()).hexdigest() != original_hash:
        raise ValueError('迁移时原检查点发生变化')
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(destination, lambda stream: torch.save(candidate, stream))
    return candidate['policy_migration']
