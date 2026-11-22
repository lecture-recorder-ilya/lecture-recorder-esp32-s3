"""Cooperative inference budget; never throttles the audio capture process."""
import json
import time
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / 'work/ai-settings.json'
DEFAULT_ECONOMICAL = False
ECONOMICAL_DUTY = .65

def economical():
    try:
        return json.loads(CONFIG.read_text()).get('economical', DEFAULT_ECONOMICAL)
    except (OSError, ValueError):
        return DEFAULT_ECONOMICAL

class Budget:
    def __init__(self, synchronize=lambda: None, clock=time.monotonic,
                 sleep=time.sleep, enabled=economical, burst=1.0, duty=ECONOMICAL_DUTY):
        self.synchronize, self.clock, self.sleep, self.enabled = synchronize, clock, sleep, enabled
        self.burst, self.duty = burst, duty
        self.started = clock()
        self.active_seconds = self.idle_seconds = 0.0

    def checkpoint(self, force=False):
        if not self.enabled():
            self.started = self.clock()
            return
        if not force and self.clock() - self.started < self.burst:
            return
        self.synchronize()
        elapsed = self.clock() - self.started
        self.active_seconds += elapsed
        delay = elapsed * (1 / self.duty - 1)
        # Short sleeps allow process shutdown and configuration changes.
        remaining = delay
        while remaining > 0 and self.enabled():
            step = min(remaining, .5)
            self.sleep(step)
            self.idle_seconds += step
            remaining -= step
        self.started = self.clock()

def streamed_text(model, tokenizer, prompt, max_tokens, sampler, budget=None):
    import mlx.core as mx
    from mlx_lm import stream_generate
    if budget is None:
        budget = Budget(synchronize=lambda: mx.synchronize(mx.gpu))
    text = []
    for response in stream_generate(model, tokenizer, prompt=prompt,
            max_tokens=max_tokens, sampler=sampler, prefill_step_size=128,
            prompt_progress_callback=lambda *_: budget.checkpoint()):
        text.append(response.text)
        budget.checkpoint()
    budget.checkpoint(force=True)
    return ''.join(text)
