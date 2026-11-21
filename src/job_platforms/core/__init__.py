"""Shared capability interfaces and edit data structures."""
from .capabilities import ProviderCapabilities
from .errors import (
    JobPlatformError, AuthenticationRequired, UpstreamError,
    ResumeNotFound, VerificationError, UnsupportedWrite, ConflictError, PartialWriteError,
)
from .patch import JsonPatchOperation, EditPlan, apply_json_patch, describe_schema

__all__ = [
    "ProviderCapabilities", "JobPlatformError", "AuthenticationRequired",
    "UpstreamError", "ResumeNotFound", "VerificationError", "UnsupportedWrite",
    "ConflictError", "PartialWriteError", "JsonPatchOperation", "EditPlan", "apply_json_patch",
    "describe_schema",
]
