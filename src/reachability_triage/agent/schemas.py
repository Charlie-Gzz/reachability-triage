"""Structured outputs every LLM node must return (validated with Pydantic)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VerdictLabel = Literal["reachable", "not_reachable", "uncertain"]


class EvidenceItem(BaseModel):
    location: str = Field(description="file:line in the application, or 'advisory'")
    explanation: str = Field(description="why this location matters, one sentence")


class Verdict(BaseModel):
    verdict: VerdictLabel
    confidence: float = Field(ge=0, le=1)
    vulnerable_symbols: list[str] = Field(default_factory=list,
                                          description="functions/classes/options the advisory says are vulnerable")
    reasoning: str = Field(description="3-6 sentences: what is vulnerable, whether the app exercises it, and how")
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=8)


class Reflection(BaseModel):
    critique: str = Field(description="the strongest argument against the verdict, and whether it holds")
    agrees: bool
    retry: bool = Field(description="true only if the verdict ignored or misread specific evidence and should be redone")
    final_verdict: VerdictLabel
    confidence: float = Field(ge=0, le=1)


class GeneratedTest(BaseModel):
    test_path: str = Field(description="repo-relative path of the new test file")
    test_id: str = Field(description="how to select just this test: pytest node id, or dotted Django test label")
    code: str = Field(description="full contents of the test file")
    rationale: str


class FileEdit(BaseModel):
    path: str
    content: str = Field(description="full new contents of the file")


class Patch(BaseModel):
    files: list[FileEdit] = Field(default_factory=list)
    rationale: str
