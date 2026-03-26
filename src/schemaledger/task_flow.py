from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import ArtifactRecord


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._artifacts: list[ArtifactRecord] = []

    def append(self, artifact: ArtifactRecord) -> None:
        self._artifacts.append(artifact)

    def list_for_task(self, task_id: str) -> tuple[ArtifactRecord, ...]:
        return tuple(artifact for artifact in self._artifacts if artifact.task_id == task_id)

    def list_task_ids(self) -> tuple[str, ...]:
        return tuple(sorted({artifact.task_id for artifact in self._artifacts}))

    def all_artifacts(self) -> tuple[ArtifactRecord, ...]:
        return tuple(self._artifacts)


class JsonlArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / "artifacts.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, artifact: ArtifactRecord) -> None:
        record = asdict(artifact)
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
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
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
                    )
                )
        return tuple(artifacts)
