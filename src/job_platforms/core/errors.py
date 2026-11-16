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
