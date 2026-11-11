"""Errors that map to an HTTP status and a message that's safe to show users."""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UpstreamError(ServiceError):
    """FoodData Central failed, couldn't be reached, or sent something unusable."""

    status_code = 502


class RateLimitedError(ServiceError):
    """FoodData Central says this API key has used up its requests for now."""

    status_code = 503


class NotConfiguredError(ServiceError):
    """The server was started without an FDC_API_KEY."""

    status_code = 503
