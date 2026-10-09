"""Only the action process loads the write secret. No public HTTP exposure yet."""

import os

from services.metricflow.secrets import read_key_file
from services.metricflow.writer import MetricFlowActionConnector


def create_action_connector() -> MetricFlowActionConnector:
    return MetricFlowActionConnector(
        read_key_file(os.environ.get("METRICFLOW_WRITE_KEY_FILE"))
    )
