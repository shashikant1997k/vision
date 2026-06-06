from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelVersion:
    """A locked, hashed model artifact. Every inference result must reference
    the model version used, and any swap is a change-control event (D-007)."""

    name: str
    path: str
    sha256: str
    validated: bool = False


class ModelRegistry:
    """Tracks locked, versioned models for the (optional) AI module and the
    neural OCR engine."""

    def __init__(self) -> None:
        self._models: dict[str, ModelVersion] = {}

    def register(self, name: str, path: str | Path, validated: bool = False) -> ModelVersion:
        p = Path(path)
        digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "absent"
        mv = ModelVersion(name=name, path=str(p), sha256=digest, validated=validated)
        self._models[name] = mv
        return mv

    def get(self, name: str) -> ModelVersion | None:
        return self._models.get(name)
