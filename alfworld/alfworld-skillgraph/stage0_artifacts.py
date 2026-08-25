"""Deterministic Stage 0 IR/candidate artifact writer."""

from __future__ import annotations

import copy
import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Iterable

from stage0_core import sha256_file


class ArtifactSafetyError(ValueError):
    """Raised if an artifact would persist an API credential."""


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        if hasattr(value, "to_dict"):
            return _plain(value.to_dict())
        return _plain(dataclasses.asdict(value))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _assert_no_secrets(value: Any, path: str = "artifact") -> None:
    secret = os.environ.get("DEEPSEEK_API_KEY")
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in {"api_key", "apikey", "authorization", "access_token"}:
                raise ArtifactSafetyError(f"credential field forbidden in {path}.{key}")
            _assert_no_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secrets(child, f"{path}[{index}]")
    elif secret and isinstance(value, str) and secret in value:
        raise ArtifactSafetyError(f"API key value found in {path}")


class ArtifactWriter:
    """Write IR, candidates, verifier audits and exact-byte hash sidecars."""

    def __init__(self, output_root: str | Path):
        self.root = Path(output_root)

    def _write_bytes(self, relative: str | Path, payload: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sidecar = Path(str(path) + ".sha256")
        sidecar.write_text(sha256_file(path) + "\n", encoding="utf-8")
        return path

    def _write_json(self, relative: str | Path, value: Any) -> Path:
        plain = _plain(value)
        _assert_no_secrets(plain)
        payload = (json.dumps(plain, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        return self._write_bytes(relative, payload)

    def _write_jsonl(self, relative: str | Path, values: Iterable[Any]) -> Path:
        plain = [_plain(value) for value in values]
        _assert_no_secrets(plain)
        payload = b"".join(
            (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            for value in plain
        )
        return self._write_bytes(relative, payload)

    def write(self, result: Any) -> dict[str, Path]:
        """Write a complete EvolutionResult-shaped object and return paths."""

        paths: dict[str, Path] = {}
        paths["failures"] = self._write_jsonl("ir/failures.jsonl", getattr(result, "failures", []))
        paths["failures_sha256"] = Path(str(paths["failures"]) + ".sha256")
        paths["preservations"] = self._write_jsonl("ir/preservations.jsonl", getattr(result, "preservations", []))
        paths["preservations_sha256"] = Path(str(paths["preservations"]) + ".sha256")
        paths["root_cause"] = self._write_json("ir/root_causes.json", getattr(result, "root_cause", None))
        paths["root_cause_sha256"] = Path(str(paths["root_cause"]) + ".sha256")
        paths["request_records"] = self._write_jsonl("ir/request_records.jsonl", getattr(result, "request_records", []))
        paths["request_records_sha256"] = Path(str(paths["request_records"]) + ".sha256")

        for label, attribute in (("structured_patch", "structured_candidate"), ("full_rewrite", "rewrite_candidate")):
            candidate = getattr(result, attribute, None)
            if candidate is not None:
                paths[f"candidate_{label}"] = self._write_json(
                    f"candidates/{label}/candidate.json",
                    candidate,
                )
                paths[f"candidate_{label}_sha256"] = Path(str(paths[f"candidate_{label}"]) + ".sha256")

        audits: list[dict] = []
        for label, attribute in (("structured_patch", "structured_verifier"), ("full_rewrite", "rewrite_verifier")):
            verifier = getattr(result, attribute, None)
            if verifier is not None:
                paths[f"verifier_{label}"] = self._write_json(f"verifier/{label}.json", verifier)
                paths[f"verifier_{label}_sha256"] = Path(str(paths[f"verifier_{label}"]) + ".sha256")
                row = _plain(verifier)
                row["candidate_label"] = label
                audits.append(row)
        structural_rows = []
        for attribute in ("structured_candidate", "rewrite_candidate"):
            candidate = getattr(result, attribute, None)
            if candidate is not None:
                structural_rows.append(_plain(candidate))
        semantic_rows = list(audits)
        paths["verifier_structural"] = self._write_json("verifier/structural.json", structural_rows)
        paths["verifier_structural_sha256"] = Path(str(paths["verifier_structural"]) + ".sha256")
        paths["verifier_semantic_blind"] = self._write_json("verifier/semantic_blind.json", semantic_rows)
        paths["verifier_semantic_blind_sha256"] = Path(str(paths["verifier_semantic_blind"]) + ".sha256")
        paths["verifier_audits"] = self._write_jsonl("verifier/audits.jsonl", audits)
        paths["verifier_audits_sha256"] = Path(str(paths["verifier_audits"]) + ".sha256")
        return paths


__all__ = ["ArtifactSafetyError", "ArtifactWriter"]
