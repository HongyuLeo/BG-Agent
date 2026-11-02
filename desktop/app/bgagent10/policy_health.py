"""Detached PPO diagnostics, observing actual score gradients without extra backward."""
import torch


class ActorHealth:
    def __init__(self, model):
        self.model = model
        self.head = getattr(model, 'score', None)
        self.parameters = [(n,p) for n,p in self.head.named_parameters() if p.requires_grad] if self.head is not None else []
        self.last_activation = None
        self.handle = None
        self.stats = None
        self.gradient_chunks = 0
        self.missing_gradient_chunks = 0
        self.group_max = {}
        self.parameter_max = {}

    def __enter__(self):
        if self.head is not None:
            tanh = [m for m in self.head.modules() if isinstance(m, torch.nn.Tanh)]
            if len(tanh) == 1:
                self.handle = tanh[0].register_forward_hook(self._capture)
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            self.handle.remove()
        self.last_activation = None

    def _capture(self, module, inputs, output):
        self.last_activation = output.detach()

    def observe_logits(self, logits):
        z = logits.detach()
        mask = torch.isfinite(z)
        n = mask.sum(-1)
        multi = n > 1
        maximum = z.masked_fill(~mask, -torch.inf).amax(-1)
        minimum = z.masked_fill(~mask, torch.inf).amin(-1)
        values = z.masked_fill(~mask, 0)
        mean = values.sum(-1) / n.clamp_min(1)
        variance = ((values - mean[:, None]).square() * mask).sum(-1) / n.clamp_min(1)
        std = variance.sqrt()
        uniform = multi & (maximum == minimum)
        dead = torch.zeros_like(multi)
        activation = self.last_activation
        if activation is not None and activation.shape[:2] == z.shape:
            legal = mask[..., None]
            saturated = ((activation.abs() == 1) | ~legal).all(-1).all(-1)
            amin = activation.masked_fill(~legal, torch.inf).amin(-2)
            amax = activation.masked_fill(~legal, -torch.inf).amax(-2)
            identical = (amin == amax).all(-1)
            dead = multi & saturated & identical
        row = torch.stack([multi.sum(), uniform.sum(), dead.sum(), (std * multi).sum()]).to(torch.float64)
        self.stats = row if self.stats is None else self.stats + row

    def observe_gradients(self):
        # Called after the existing loss.backward, before global norm clipping.
        # No new loss, backward, optimizer step or model-state update is introduced.
        self.gradient_chunks += 1
        grads = [(name, p.grad.detach()) for name, p in self.parameters if p.grad is not None]
        if len(grads) != len(self.parameters) or not grads:
            self.missing_gradient_chunks += 1
            return
        maxima = []
        for name, grad in grads:
            value = grad.abs().amax()
            self.parameter_max[name] = value if name not in self.parameter_max else torch.maximum(self.parameter_max[name], value)
            maxima.append(value)
            key = name.split('.')[0]
            self.group_max[key] = value if key not in self.group_max else torch.maximum(self.group_max[key], value)
        maximum = torch.stack(maxima).amax()
        if not hasattr(self, 'gradient_max'):
            self.gradient_max = maximum
            self.zero_chunks = (maximum == 0).to(torch.int64)
        else:
            self.gradient_max = torch.maximum(self.gradient_max, maximum)
            self.zero_chunks += (maximum == 0).to(torch.int64)

    def summary(self):
        counts = [0., 0., 0., 0.] if self.stats is None else self.stats.cpu().tolist()
        multi, uniform, dead, std_sum = counts
        gradient_max = float(self.gradient_max.cpu()) if hasattr(self, 'gradient_max') else None
        zero_chunks = int(self.zero_chunks.cpu()) if hasattr(self, 'zero_chunks') else 0
        all_grad_zero = (self.gradient_chunks > 0 and self.missing_gradient_chunks == 0
                         and zero_chunks == self.gradient_chunks and gradient_max == 0.)
        numeric_witness = multi > 0 and uniform == multi and dead == multi
        fault = bool(numeric_witness and all_grad_zero)
        return dict(schema='bgagent10-actor-health-v1', multi_legal_samples=int(multi),
                    exact_uniform_samples=int(uniform), exact_uniform_fraction=uniform/multi if multi else None,
                    exact_dead_tanh_identical_samples=int(dead), mean_legal_logit_std=std_sum/multi if multi else None,
                    gradient_chunks=self.gradient_chunks, missing_score_gradient_chunks=self.missing_gradient_chunks,
                    zero_score_gradient_chunks=zero_chunks, score_gradient_absmax=gradient_max,
                    score_parameter_group_gradient_absmax={k: float(v.cpu()) for k,v in self.group_max.items()},
                    score_parameter_gradient_absmax={k: float(v.cpu()) for k,v in self.parameter_max.items()},
                    explicit_numeric_collapse=fault, suspected_numeric_collapse=bool(numeric_witness and not fault),
                    detection='All actually optimized multi-legal rows exact-uniform, all legal Tanh vectors identical exact+/-1, and every actual score gradient exactly zero. No low-entropy or mere finite-loss criterion.',
                    diagnostic_only_samples='PPO objective timesteps across epochs (may repeat a decision); excludes recurrent burn-in and single-legal-action rows')
