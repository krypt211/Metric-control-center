"""Errors contain neither credentials nor upstream response bodies."""


class MetricFlowError(Exception):
    pass


class ConfigurationError(MetricFlowError):
    pass


class APIError(MetricFlowError):
    def __init__(self, status_code: int, message: str = "MetricFlow request failed"):
        self.status_code = status_code
        super().__init__(f"{message} (HTTP {status_code})")


class AuthenticationError(APIError):
    pass


class PermissionDenied(APIError):
    pass


class SubscriptionRequired(APIError):
    pass


class RateLimitExceeded(APIError):
    def __init__(self, retry_after_seconds: int | None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(429, "MetricFlow request limit reached")


class TransportUnavailable(MetricFlowError):
    pass


class InvalidResponse(MetricFlowError):
    pass


class ActionOutcomeUnknown(MetricFlowError):
    """Do not resend automatically: upstream might have executed the command."""
