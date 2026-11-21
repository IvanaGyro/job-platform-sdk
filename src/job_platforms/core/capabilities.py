"""Explicit platform capabilities; not every provider implements every operation."""
from dataclasses import dataclass, asdict
from typing import Protocol, Any

@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    list_resumes: bool = False
    get_resume: bool = False
    create_resume: bool = False
    plan_edit: bool = False
    save_edit: bool = False
    upload_attachments: bool = False
    apply_jobs: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

class ResumeProvider(Protocol):
    async def list_resumes(self) -> list[dict]: ...
    async def get_resume(self, resume_id: str) -> dict: ...
    async def create_resume(self) -> dict: ...
