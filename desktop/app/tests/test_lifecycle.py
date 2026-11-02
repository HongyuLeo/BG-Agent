from bgagent10.lifecycle import judge_promotion, quarantine_bug, sample_allowed


def report(policy, n=4, rank=1):
    return dict(checkpoint_sha=policy, engine_hash='engine', opponent_hash='pool',
                lobbies=[dict(episode_id=str(i), terminal_reason='normal_elimination',
                              split='evaluation', rank=rank, policy_seats=1) for i in range(n)])


def protocol():
    return dict(candidate_sha='candidate', champion_sha='champion', engine_hash='engine',
                opponent_hash='pool', independent_lobbies=4, minimum_gain=.05, alpha=.05,
                statistic='bounded independent lobby intervals')


def test_small_lucky_evaluation_is_not_promotion():
    result = judge_promotion(protocol(), report('candidate'), report('champion', rank=8))
    assert not result['accepted']


def test_duplicate_and_multi_seat_results_are_rejected():
    candidate = report('candidate')
    candidate['lobbies'][1]['episode_id'] = '0'
    candidate['lobbies'][0]['policy_seats'] = 8
    result = judge_promotion(protocol(), candidate, report('champion'))
    assert 'candidate_duplicate_lobby' in result['reasons']
    assert 'candidate_invalid_lobby' in result['reasons']


def test_bug_quarantines_all_seats_and_unknown_scope(tmp_path):
    bug = quarantine_bug(tmp_path, 'rule-001', ['old-engine'], 'reward changed')
    assert not sample_allowed(dict(engine_hash='old-engine', episode_id='any'), [bug])
    assert sample_allowed(dict(engine_hash='new-engine', episode_id='any'), [bug])
