from pathlib import Path

import pytest

from tests.unit.mocks.requesters import QueueRequester

FILES = Path(__file__).parent / "files"
RESPONSES = FILES / "responses"


@pytest.fixture()
def queue_requester() -> QueueRequester:
    return QueueRequester()
