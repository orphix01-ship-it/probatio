"""Content-addressed certificates and an append-only, hash-chained ledger.

Every ledger line is JSON with ``seq``, ``prev`` (hash of the previous entry),
``type``, ``body`` and ``hash`` = sha256(canonical(seq, prev, type, body)).
Optional Ed25519 signatures (``sig``) bind entries to an operator key when
``PROBATIO_SIGNING_KEY`` (hex 32-byte seed) is set and ``cryptography`` is
installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

from .util import canonical_json, hash_obj, now_iso, sha256_hex

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

GENESIS = "0" * 64


class Ledger:
    def __init__(self, results_dir: Path):
        self.dir = Path(results_dir)
        self.certs = self.dir / "certs"
        self.path = self.dir / "ledger.jsonl"
        self.certs.mkdir(parents=True, exist_ok=True)
        self._signer = _load_signer()

    # ---- certificates -------------------------------------------------
    def store_certificate(self, cert: dict[str, Any]) -> str:
        h = hash_obj(cert)
        p = self.certs / f"{h}.json"
        if not p.exists():
            p.write_text(json.dumps(cert, indent=2, sort_keys=True) + "\n")
        return h

    def load_certificate(self, ref: str) -> dict[str, Any]:
        p = Path(ref)
        if not p.exists():
            p = self.certs / f"{ref}.json"
        try:
            cert = json.loads(p.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"certificate {p.name} is corrupted (not valid JSON): {exc}") from None
        actual = hash_obj(cert)
        expected = p.stem
        if len(expected) == 64 and actual != expected:
            raise ValueError(f"certificate {p.name} content hash mismatch")
        return cert

    def iter_certificates(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for p in sorted(self.certs.glob("*.json")):
            yield p.stem, self.load_certificate(str(p))

    # ---- ledger -------------------------------------------------------
    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append(self, type_: str, body: dict[str, Any]) -> dict[str, Any]:
        """Append under an exclusive lock so concurrent runs cannot fork the chain."""
        with (self.dir / ".ledger.lock").open("a") as lock:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                ents = self.entries()
                seq = len(ents)
                prev = ents[-1]["hash"] if ents else GENESIS
                core = {"seq": seq, "prev": prev, "type": type_, "body": body, "time": now_iso()}
                entry = dict(core, hash=hash_obj(core))
                if self._signer:
                    entry["sig"] = self._signer.sign(bytes.fromhex(entry["hash"])).hex()
                    entry["pubkey"] = self._pubkey_hex
                with self.path.open("a") as fh:
                    fh.write(canonical_json(entry) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            finally:
                if fcntl:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        return entry

    def audit(self) -> list[str]:
        """Return a list of problems; empty means the chain is intact."""
        problems: list[str] = []
        prev = GENESIS
        for i, e in enumerate(self.entries()):
            core = {k: e[k] for k in ("seq", "prev", "type", "body", "time") if k in e}
            if e.get("seq") != i:
                problems.append(f"entry {i}: sequence number {e.get('seq')} out of order")
            if e.get("prev") != prev:
                problems.append(f"entry {i}: broken chain (prev hash mismatch)")
            if hash_obj(core) != e.get("hash"):
                problems.append(f"entry {i}: content altered (hash mismatch)")
            if "sig" in e and not _verify_sig(e):
                problems.append(f"entry {i}: invalid signature")
            if e.get("type") == "certificate":
                ref = e["body"].get("cert")
                cp = self.certs / f"{ref}.json"
                if not cp.exists():
                    problems.append(f"entry {i}: referenced certificate {ref[:12]} missing")
                else:
                    try:
                        altered = sha256_hex(canonical_json(json.loads(cp.read_bytes().decode("utf-8")))) != ref
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        altered = True  # unreadable counts as altered, never as a crash
                    if altered:
                        problems.append(f"entry {i}: certificate {ref[:12]} altered")
            prev = e.get("hash")
        return problems

    @property
    def _pubkey_hex(self) -> str:
        from cryptography.hazmat.primitives import serialization
        return self._signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def _load_signer():
    seed = os.environ.get("PROBATIO_SIGNING_KEY")
    if not seed:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))


def _verify_sig(e: dict[str, Any]) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(e["pubkey"])).verify(
            bytes.fromhex(e["sig"]), bytes.fromhex(e["hash"]))
        return True
    except Exception:
        return False
