import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class Policy(BaseModel):
    policy_id: str
    name: str
    category: str
    description: str
    requirement: str
    severity: str
    guidance: Optional[str] = None

class PolicyService:
    def __init__(self, policy_file_path: str = "policies/policies.json"):
        self.policy_file_path = policy_file_path
        self._policies: List[Policy] = []
        self.load_policies()

    def load_policies(self) -> List[Policy]:
        path = Path(self.policy_file_path)
        if not path.is_file():
            # Try resolving relative to repository root
            project_root = Path(__file__).resolve().parent.parent.parent
            candidate = project_root / self.policy_file_path
            if candidate.is_file():
                path = candidate
            else:
                candidate_in_policies = project_root / "policies" / path.name
                if candidate_in_policies.is_file():
                    path = candidate_in_policies
                else:
                    raise FileNotFoundError(f"Policy file not found: {self.policy_file_path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._policies = [Policy(**item) for item in data]
        return self._policies

    def get_all_policies(self) -> List[Policy]:
        if not self._policies:
            self.load_policies()
        return self._policies

    def get_policy_by_id(self, policy_id: str) -> Optional[Policy]:
        for p in self.get_all_policies():
            if p.policy_id.upper() == policy_id.upper():
                return p
        return None
