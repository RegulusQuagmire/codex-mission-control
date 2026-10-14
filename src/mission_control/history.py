"""Only observed, validator-backed counts. Caller owns the interprocess lease."""
from __future__ import annotations

import json
from pathlib import Path

from .state import state_exists, load_state, save_state


class History:
    def __init__(self, records: dict | None = None, observations: set[str] | None = None, quality_records: dict | None = None):
        self.records = {} if records is None else records
        self.observations = set(observations or ())
        # Legacy aggregate counts lack validation-kind provenance. Keep them
        # readable, but do not silently promote them into Stage 13 evidence.
        self.quality_records = {} if quality_records is None else quality_records

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
        quality=self.quality_records.setdefault(key,{'success':0,'failure':0})
        quality['success' if success else 'failure']+=1

    def record_once(self, observation: str, model, effort, complexity, success: bool):
        if not isinstance(observation, str) or not observation:
            raise ValueError("Observation ID is required")
        if observation not in self.observations:
            self.record(model, effort, complexity, success)
            self.observations.add(observation)

    def record_validated(self, observation, model, effort, complexity, result, *, legacy_observation=None):
        # Timeouts, access failures, cancellation and infrastructure uncertainty
        # are not a model quality observation, even if a caller supplied False.
        if result.get('kind') not in {'quality','test_failure'}:
            return
        if legacy_observation is not None and legacy_observation in self.observations:
            self.observations.add(observation)
            return  # Preserve old dedup; absent provenance is not promoted.
        self.record_once(observation, model, effort, complexity, result['passed'])

    @staticmethod
    def turn_observation(thread_id,turn_id):
        return json.dumps(['turn',thread_id,turn_id],separators=(',',':'))

    def evidence(self, model, effort, complexity):
        record=self.quality_records.get(self._key(model,effort,complexity),{})
        success,failure = record.get('success',0),record.get('failure',0)
        total=success+failure
        unreliable=total>=8 and 10*(failure+2)>=7*(total+4)
        status='insufficient' if total<8 else 'repeated_failure' if unreliable else 'supported' if success>failure else 'mixed'
        return {'success':success,'failure':failure,'samples':total,'minimumSamples':8,
                'status':status,'unreliable':unreliable}

    def save(self, path: Path):
        save_state(path, {"version": 1, "records": self.records, "observations": sorted(self.observations),
                          "qualityRecords":self.quality_records})

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
        quality=data.get('qualityRecords',{})
        if not isinstance(quality,dict):raise ValueError('Invalid quality history')
        for key,record in quality.items():
            if (key not in data['records'] or not isinstance(record,dict)
                or set(record)!={'success','failure'}
                or any(type(v) is not int or v<0 or v>data['records'][key][k] for k,v in record.items())):
                raise ValueError('Invalid quality history')
        return cls(data["records"], set(observations),quality)
