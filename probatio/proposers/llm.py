"""AI proposers.

``LLMProposer`` asks a model for candidates directly as JSON.
``ProgramEvolutionProposer`` (FunSearch / AlphaEvolve style) keeps a population
of generator programs, asks the model to improve the best ones, runs each
program in the sandbox and lets the checker score its output.

Both are untrusted. Model output is parsed defensively; programs run only in
the sandbox; the API key is read from the environment, never logged, never
passed to the sandbox.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

from ..sandbox import run_program
from ..util import sha256_hex
from .base import Context, Feedback, Proposer


class AnthropicClient:
    """Minimal Messages API client over HTTPS (standard library only)."""

    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str | None = None):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.model = model or os.environ.get("PROBATIO_MODEL", "claude-sonnet-5-5")
        self.price_in = float(os.environ.get("PROBATIO_PRICE_IN_PER_MTOK", "0"))
        self.price_out = float(os.environ.get("PROBATIO_PRICE_OUT_PER_MTOK", "0"))

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> tuple[str, dict[str, Any]]:
        body = json.dumps({"model": self.model, "max_tokens": max_tokens, "system": system,
                           "messages": [{"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01",
            "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        cost = (usage.get("input_tokens", 0) * self.price_in +
                usage.get("output_tokens", 0) * self.price_out) / 1e6
        return text, {"model": data.get("model", self.model), "usage": usage, "cost_usd": cost}


class LocalClient:
    """Open-weight model served on this machine by Ollama: no key, no network, $0.

    Only loopback hosts are accepted, so prompts and outputs never leave the
    machine. The model's content digest is recorded with every run so the
    exact weights are identifiable later; a fixed seed makes sampling repeatable
    for a given model, prompt and Ollama version.
    """

    def __init__(self, model: str | None = None, host: str | None = None, seed: int = 0,
                 temperature: float = 0.8, timeout: float = 600):
        self.host = (host or os.environ.get("PROBATIO_LOCAL_HOST", "http://127.0.0.1:11434")).rstrip("/")
        hostname = urllib.parse.urlparse(self.host).hostname or ""
        if not _is_loopback(hostname):
            raise RuntimeError(f"local model host must be loopback, got {hostname!r}")
        self.model = model or os.environ.get("PROBATIO_LOCAL_MODEL", "qwen2.5-coder:14b")
        self.seed, self.temperature, self.timeout = seed, temperature, timeout
        self.digest = self._digest()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(self.host + path, data=json.dumps(payload).encode(), method="POST",
                                     headers={"content-type": "application/json"})
        # Explicit no-proxy opener: a loopback request must never be routed through a proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def _digest(self) -> str | None:
        try:
            req = urllib.request.Request(self.host + "/api/tags")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=10) as resp:
                tags = json.loads(resp.read())
        except Exception as exc:
            raise RuntimeError(f"no local model server at {self.host} ({exc}); start it with `ollama serve`") from exc
        for m in tags.get("models", []):
            if m.get("name") == self.model or m.get("model") == self.model:
                return m.get("digest")
        raise RuntimeError(f"model {self.model!r} is not pulled; run `ollama pull {self.model}`")

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> tuple[str, dict[str, Any]]:
        data = self._post("/api/chat", {
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"seed": self.seed, "temperature": self.temperature, "num_predict": max_tokens}})
        self.seed += 1  # next call samples differently but the sequence stays repeatable
        text = (data.get("message") or {}).get("content", "")
        usage = {"input_tokens": data.get("prompt_eval_count", 0), "output_tokens": data.get("eval_count", 0)}
        return text, {"model": f"{self.model}@{(self.digest or '')[:12]}", "usage": usage, "cost_usd": 0.0}


def _is_loopback(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def make_client(backend: str = "anthropic", model: str | None = None, seed: int = 0,
                temperature: float = 0.8):
    if backend == "local":
        return LocalClient(model=model, seed=seed, temperature=temperature)
    if backend == "anthropic":
        return AnthropicClient(model=model)
    raise ValueError(f"unknown model backend {backend!r}")


SYSTEM = ("You are a research mathematician proposing candidates for a machine checker. "
          "Every candidate you produce will be verified exactly; unverifiable claims are "
          "worthless. Be creative and exploit structure (symmetry, algebra, known "
          "constructions). Output only what is requested.")


def _describe(problem: dict[str, Any], ctx: Context) -> str:
    lines = [f"PROBLEM {problem['id']}", problem["statement"],
             f"Candidate format: {json.dumps(problem.get('candidate_format', {}))}",
             f"Objective: {problem['objective']['sense']} {problem['objective'].get('field', '')}"]
    if problem.get("known_best"):
        lines.append(f"Recorded best known: {json.dumps(problem['known_best'])}")
    if ctx.best:
        lines.append("Best verified candidates so far (value, candidate):")
        for v, c in ctx.best[:5]:
            lines.append(f"  {v}: {json.dumps(_compact(c))}")
    if ctx.recent_failures:
        lines.append("Recent rejections from the checker:")
        for fb in ctx.recent_failures[-5:]:
            lines.append(f"  {json.dumps(_compact(fb.candidate))[:200]} -> {fb.reason[:160]}")
    return "\n".join(lines)


def _compact(c: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in c.items() if k != "generators"} if "seed" in c else c


def _extract_json(text: str) -> Any:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    raw = m.group(1) if m else text
    start = min([i for i in (raw.find("["), raw.find("{")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON found")
    return json.loads(raw[start:])


class LLMProposer(Proposer):
    name = "llm"

    def __init__(self, *a, client=None, **kw):
        super().__init__(*a, **kw)
        self.client = client or make_client(self.opts.get("backend", "anthropic"), self.opts.get("model"),
                                            seed=int(self.opts.get("seed", 0)),
                                            temperature=float(self.opts.get("temperature", 0.8)))
        self.meta["model"] = getattr(self.client, "model", "unknown")
        self.meta["backend"] = self.opts.get("backend", "anthropic")
        if getattr(self.client, "digest", None):
            self.meta["model_digest"] = self.client.digest
        self.calls = 0
        self.max_calls = int(self.opts.get("max_calls", 0))

    @property
    def done(self) -> bool:  # call budget reached
        return bool(self.max_calls) and self.calls >= self.max_calls

    @done.setter
    def done(self, value):  # base class assigns done; the call budget decides instead
        pass

    def propose(self, ctx: Context, batch: int):
        user = (_describe(self.problem, ctx) +
                f"\n\nPropose {batch} new, distinct candidates likely to beat the best so far. "
                "Return a JSON array of candidate objects in the candidate format, nothing else.")
        text, info = self.client.complete(SYSTEM, user)
        self._account(user, info)
        try:
            data = _extract_json(text)
        except (ValueError, json.JSONDecodeError):
            return []
        items = data if isinstance(data, list) else [data]
        return [self.space.normalize(c) for c in items if isinstance(c, dict)][:batch]

    def _account(self, prompt: str, info: dict[str, Any]):
        self.calls += 1
        self.cost_usd += info.get("cost_usd", 0.0)
        self.meta.update(model=info.get("model"), calls=self.calls,
                         last_prompt_sha256=sha256_hex(prompt), cost_usd=round(self.cost_usd, 6))


PROGRAM_TEMPLATE = '''import json, itertools, random

def generate():
    """Return a list of candidate objects in the problem's candidate format."""
    return []

print(json.dumps(generate()))
'''


class ProgramEvolutionProposer(LLMProposer):
    """Evolve generator programs. Each program runs in the sandbox."""
    name = "program_evolution"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.population: list[tuple[float, str]] = [(-1e9, PROGRAM_TEMPLATE)]
        self._last_program: str | None = None
        self.meta["sandbox_runs"] = 0

    def propose(self, ctx: Context, batch: int):
        parents = sorted(self.population, key=lambda t: -t[0])[:2]
        user = (_describe(self.problem, ctx) +
                "\n\nHere are the best generator programs so far (score, code):\n" +
                "\n\n".join(f"# score {s}\n```python\n{p}\n```" for s, p in parents) +
                f"\n\nWrite an improved Python program (standard library only, no network, no "
                f"files) that prints one JSON array of up to {batch} candidates. "
                "Return only the program in a ```python block.")
        text, info = self.client.complete(SYSTEM, user)
        self._account(user, info)
        m = re.search(r"```python\s*(.*?)```", text, flags=re.S)
        program = m.group(1) if m else text
        self._last_program = program
        res = run_program(program, timeout_s=float(self.opts.get("program_timeout", 20)))
        self.meta["sandbox_runs"] += 1
        self.meta["network_isolated"] = res.network_isolated
        if not res.ok or not isinstance(res.output, list):
            self.population.append((-1e9, program))
            return []
        self.meta["program_sha256"] = sha256_hex(program)
        return [self.space.normalize(c) for c in res.output if isinstance(c, dict)][:batch]

    def observe(self, feedback: list[Feedback]):
        vals = [fb.value for fb in feedback if fb.valid and fb.value is not None]
        if self._last_program is not None:
            score = max(vals) if vals else -1e9
            self.population.append((score, self._last_program))
            self.population = sorted(self.population, key=lambda t: -t[0])[:20]
