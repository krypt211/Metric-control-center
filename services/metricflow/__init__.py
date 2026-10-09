"""Read-only default import. Write connector is constructed in services.actions."""

from .reader import MetricFlowConnector

__all__ = ["MetricFlowConnector"]
