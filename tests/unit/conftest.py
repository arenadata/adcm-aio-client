import pytest

from tests.unit.mocks.requesters import QueueRequester


@pytest.fixture()
def queue_requester() -> QueueRequester:
    return QueueRequester()
