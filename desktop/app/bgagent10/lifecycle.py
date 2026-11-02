"""Auditable model promotion and whole-lobby contamination tracking.

Neither a passing test nor a low training loss promotes a deployed model.
The protocol is written before evaluation. Checkpoints are immutable assets.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temporary.open('w', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def quarantine_bug(registry, bug_id, engine_hashes, reason, affected_episode_ids=None):
    """Default unknown contamination scope to ALL lobbies of affected versions."""
    if not bug_id or not reason or not engine_hashes:
        raise ValueError('bug ID, reason and affected versions are required')
    registry = Path(registry)
    record = {
        'bug_id': bug_id, 'reason': reason, 'engine_hashes': sorted(set(engine_hashes)),
        'episode_ids': sorted(set(affected_episode_ids)) if affected_episode_ids is not None else None,
        'scope': 'entire_lobby_all_seats', 'promotion_blocked': True,
        'status': 'open', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'recovery': 'repair regression; compare historical checkpoints under repaired rules; resample; reevaluate',
    }
    path = registry / (hashlib.sha256(bug_id.encode('utf8')).hexdigest() + '.json')
    if path.exists():
        previous = json.loads(path.read_text('utf8'))
        if any(previous[key] != record[key] for key in ('bug_id', 'reason', 'engine_hashes', 'episode_ids')):
            raise ValueError('bug identity already exists with different scope; append a new revision')
        return previous
    atomic_write(path, record)
    return record


def sample_allowed(sample, bugs):
    """A card-ID match is never used as the contamination boundary."""
    for bug in bugs:
        if bug['status'] != 'open' or sample['engine_hash'] not in bug['engine_hashes']:
            continue
        if bug['episode_ids'] is None or sample['episode_id'] in bug['episode_ids']:
            return False
    return True


def register_protocol(path, *, engine_hash, opponent_hash, candidate_sha, champion_sha,
                      independent_lobbies=2000, minimum_gain=.05, alpha=.05):
    if independent_lobbies < 2 or not 0 < alpha < 1 or minimum_gain < 0:
        raise ValueError('invalid preregistered evaluation parameters')
    value = dict(schema='bgagent10-promotion-v1', engine_hash=engine_hash,
                 opponent_hash=opponent_hash, candidate_sha=candidate_sha,
                 champion_sha=champion_sha, independent_lobbies=independent_lobbies,
                 minimum_gain=minimum_gain, alpha=alpha,
                 statistic='one tested seat per lobby; independent-arm bounded Hoeffding interval',
                 created_utc=datetime.now(timezone.utc).isoformat())
    if Path(path).exists():
        raise FileExistsError('protocol immutable; use a new evaluation identifier')
    atomic_write(path, value)
    return value


def judge_promotion(protocol, candidate, champion, *, open_bugs=(), release_gates=None):
    """Require independently collected normal lobbies and a predeclared gain.

    Confidence is deliberately conservative; paired seeds alone do not prove
    identical random events. Independent samples are complete lobbies, not seats.
    """
    reasons = []
    if open_bugs:
        reasons.append('unresolved_contamination')
    for name, report, expected in (('candidate', candidate, protocol['candidate_sha']),
                                   ('champion', champion, protocol['champion_sha'])):
        if report.get('checkpoint_sha') != expected:
            reasons.append(name + '_checkpoint_mismatch')
        for key in ('engine_hash', 'opponent_hash'):
            if report.get(key) != protocol[key]:
                reasons.append(name + '_' + key + '_mismatch')
        rows = report.get('lobbies', [])
        if len(rows) < protocol['independent_lobbies']:
            reasons.append(name + '_insufficient_lobbies')
        if len({r.get('episode_id') for r in rows}) != len(rows):
            reasons.append(name + '_duplicate_lobby')
        for row in rows:
            if (row.get('terminal_reason') != 'normal_elimination'
                    or row.get('split') != 'evaluation'
                    or not 1 <= row.get('rank', 0) <= 8
                    or row.get('policy_seats') != 1):
                reasons.append(name + '_invalid_lobby')
                break
    if reasons:
        return {'accepted': False, 'reasons': reasons, 'gain': None}
    c = [r['rank'] for r in candidate['lobbies']]
    b = [r['rank'] for r in champion['lobbies']]
    gain = sum(b) / len(b) - sum(c) / len(c)
    margin = 7 * (math.sqrt(math.log(4 / protocol['alpha']) / (2 * len(b)))
                  + math.sqrt(math.log(4 / protocol['alpha']) / (2 * len(c))))
    if gain - margin <= protocol['minimum_gain']:
        reasons.append('minimum_independent_gain_not_established')
    if release_gates is not None:
        reasons.extend('gate_' + name for name, passed in release_gates.items() if passed is not True)
    return {'accepted': not reasons, 'reasons': reasons, 'gain': gain,
            'ci_low': gain - margin, 'ci_high': gain + margin,
            'method': protocol['statistic'], 'independent_lobbies': [len(c), len(b)]}


def publish_champion(registry_path, checkpoint_path, decision, protocol_path):
    if decision.get('accepted') is not True:
        raise ValueError('candidate has not passed promotion')
    protocol = json.loads(Path(protocol_path).read_text('utf8'))
    actual = file_sha(checkpoint_path)
    if actual != protocol['candidate_sha']:
        raise ValueError('checkpoint changed since preregistration')
    registry_path = Path(registry_path)
    previous = json.loads(registry_path.read_text('utf8')) if registry_path.exists() else None
    atomic_write(registry_path, dict(checkpoint=str(Path(checkpoint_path).resolve()),
                                    sha256=actual, protocol=str(Path(protocol_path).resolve()),
                                    decision=decision, previous=previous))
