from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from .models import ArtifactRecord


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._artifacts: list[ArtifactRecord] = []
        self._lock = RLock()

    def append(self, artifact: ArtifactRecord) -> None:
        with self._lock:
            self._artifacts.append(artifact)

    def list_for_task(self, task_id: str) -> tuple[ArtifactRecord, ...]:
        with self._lock:
            return tuple(artifact for artifact in self._artifacts if artifact.task_id == task_id)

    def list_task_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted({artifact.task_id for artifact in self._artifacts}))

    def all_artifacts(self) -> tuple[ArtifactRecord, ...]:
        with self._lock:
            return tuple(self._artifacts)


class JsonlArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / "artifacts.jsonl"
        self._lock = RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, artifact: ArtifactRecord) -> None:
        record = asdict(artifact)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_for_task(self, task_id: str) -> tuple[ArtifactRecord, ...]:
        return tuple(
            artifact
            for artifact in self.all_artifacts()
            if artifact.task_id == task_id
        )

    def list_task_ids(self) -> tuple[str, ...]:
        return tuple(sorted({artifact.task_id for artifact in self.all_artifacts()}))

    def all_artifacts(self) -> tuple[ArtifactRecord, ...]:
        artifacts: list[ArtifactRecord] = []
        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    artifacts.append(
                        ArtifactRecord(
                            artifact_id=str(payload["artifact_id"]),
                            task_id=str(payload["task_id"]),
                            artifact_type=str(payload["artifact_type"]),
                            payload=dict(payload["payload"]),
                            recorded_at=str(payload.get("recorded_at") or _legacy_recorded_at(line_number)),
                        )
                    )
        return tuple(artifacts)


def _legacy_recorded_at(line_number: int) -> str:
    base = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=line_number)
    return base.isoformat(timespec="milliseconds").replace("+00:00", "Z")
