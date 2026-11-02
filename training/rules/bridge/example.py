"""Run with the pinned C interpreter. No debug/view or private state is policy input."""
from backend import Backend
import json

def main():
 b=Backend(seed=7,config={'max_turns':1},episode_id='operator-example')
 while not b.observe()['diagnostics']['done']:
  public=b.observe();actions=b.legal_actions()
  selected=next((a for a in actions if a['index']==0),actions[0])
  b.step(selected)
 # Trusted driver only: exact private snapshot and independent copy.
 private=b.snapshot();branch=b.copy();assert branch.snapshot()==private
 terminal=b.terminal_record();assert terminal['private_snapshot']==private
 print(json.dumps({'diagnostics':terminal['diagnostics'],'terminal_observation_retained':True,
                   'private_state_not_policy_input':True,'exact_copy':True},ensure_ascii=False))
if __name__=='__main__':main()
