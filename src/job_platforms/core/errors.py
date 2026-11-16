"""Safe domain errors that do not include personal data or raw API bodies."""

class JobPlatformError(Exception):
    """Base SDK exception."""

class AuthenticationRequired(JobPlatformError):
    """No valid authenticated provider browser session."""

class UpstreamError(JobPlatformError):
    def __init__(self, endpoint: str, status: int):
        self.endpoint = endpoint
        self.status = status
        super().__init__(f"Provider returned HTTP {status} for {endpoint}")

class ResumeNotFound(JobPlatformError):
    """Resume version is not available."""

class VerificationError(JobPlatformError):
    """A write may have occurred but cannot yet be verified. Do not retry blindly."""

class UnsupportedWrite(JobPlatformError):
    """Persistence for this operation is not yet verified."""

class ConflictError(JobPlatformError):
    """Resume changed since the read/edit plan was prepared."""


class PartialWriteError(VerificationError):
    """One or more sections were written before a later section failed.

    The failed section's remote status is uncertain; callers must not retry
    the full patch without reading the resume again. No values are attached.
    """

    def __init__(self, verified_sections: list[str], failed_section: str):
        self.verified_sections = list(verified_sections)
        self.failed_section = failed_section
        super().__init__("Multi-section save only partially verified; inspect before retrying.")
