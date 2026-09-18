from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class Finding:
    start: int
    end: int
    quote: str
    category: str
    source: str
    confidence: float
    replacement: str | None = None
    status: str = "pending"

    def to_dict(self):
        return asdict(self)


@dataclass
class AnalysisResult:
    plain_text: str
    findings: List[Finding] = field(default_factory=list)
    warnings: list = field(default_factory=list)
