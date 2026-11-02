"""Offline checks after bootstrap; no clients, downloads or long training."""
import copy, itertools, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portable_runtime import ROOT, verify_assets, metadata, read
from bgagent10.cloud_schedule import training_batches

class ReleaseChecks(unittest.TestCase):
    def test_source_integrity(self): verify_assets()
    def test_bounded_and_continuous_schedule(self):
        cfg = dict(rounds=1, games_per_round=2, workers=1, eval_every_games=0)
        self.assertEqual(list(training_batches(cfg, 0)), [(0,1,False),(0,1,True)])
        cfg.update(rounds=0, games_per_round=3, workers=2, eval_every_games=2)
        rows = list(itertools.islice(training_batches(cfg, 1), 8))
        self.assertTrue(all(1 <= count <= 2 and not final for _, count, final in rows))
        self.assertEqual(rows[0], (0,1,False))
    def test_strict_scratch_checkpoint(self):
        import torch
        from bgagent10.encoding import CardCatalog
        from bgagent10.model import build_checkpoint_model
        saved = torch.load(ROOT/'models/scratch-initial.pt', map_location='cpu', weights_only=False)
        self.assertEqual(saved['counters']['completed_games'], 0)
        catalog = CardCatalog(ROOT/'rules'); meta = metadata()
        model = build_checkpoint_model(saved, catalog, meta)
        self.assertEqual(model.preset, saved['config']['model_preset'])
        for key in ('binding', 'catalog', 'contract'):
            invalid = dict(saved); invalid[key] = dict(saved[key], unexpected='mismatch')
            with self.assertRaises(ValueError): build_checkpoint_model(invalid, catalog, meta)

if __name__ == '__main__': unittest.main()
