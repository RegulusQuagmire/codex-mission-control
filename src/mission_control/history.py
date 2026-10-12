"""Only observed, validator-backed counts. Caller owns the interprocess lease."""
from __future__ import annotations

import json
from pathlib import Path

from .state import state_exists, load_state, save_state


class History:
    def __init__(self, records: dict | None = None, observations: set[str] | None = None):
        self.records = {} if records is None else records
        self.observations = set(observations or ())

    @staticmethod
    def _key(model, effort, complexity):
        name = getattr(complexity, "name", str(complexity))
        return json.dumps([model, effort, name], separators=(",", ":"))

    def count(self, model, effort, complexity) -> tuple[int, int]:
        record = self.records.get(self._key(model, effort, complexity), {})
        return record.get("success", 0), record.get("failure", 0)

    def record(self, model, effort, complexity, success: bool):
        if type(success) is not bool:
            raise ValueError("History result must be a boolean")
        key = self._key(model, effort, complexity)
        record = self.records.setdefault(key, {"success": 0, "failure": 0})
        record["success" if success else "failure"] += 1

    def record_once(self, observation: str, model, effort, complexity, success: bool):
        if not isinstance(observation, str) or not observation:
            raise ValueError("Observation ID is required")
        if observation not in self.observations:
            self.record(model, effort, complexity, success)
            self.observations.add(observation)

    def save(self, path: Path):
        save_state(path, {"version": 1, "records": self.records, "observations": sorted(self.observations)})

    @classmethod
    def load(cls, path: Path) -> History:
        if not state_exists(path):
            return cls()
        data = load_state(path)
        if data.get("version") != 1 or not isinstance(data.get("records"), dict):
            raise ValueError("Unsupported routing history format")
        for key, record in data["records"].items():
            parts = json.loads(key)
            if (not isinstance(parts, list) or len(parts) != 3
                    or not all(isinstance(part, str) and part for part in parts)
                    or parts[2] not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
                    or not isinstance(record, dict)
                    or set(record) != {"success", "failure"}
                    or any(type(value) is not int or value < 0 for value in record.values())):
                raise ValueError("Invalid observed routing history")
        observations = data.get("observations", [])
        if not isinstance(observations, list) or any(not isinstance(item, str) or not item for item in observations):
            raise ValueError("Invalid routing observation IDs")
        return cls(data["records"], set(observations))
