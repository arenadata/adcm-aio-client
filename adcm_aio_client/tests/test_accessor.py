from contextlib import suppress

import pytest

from adcm_aio_client.core.exceptions import ObjectDoesNotExistError
from adcm_aio_client.core.objects import ClusterNode
from adcm_aio_client.tests.mocks import MockRequester


@pytest.mark.asyncio
class TestClusterNode:
    async def test_get_single_object_success(self):
        accessor = ClusterNode("clusters", requester=MockRequester(base_url="http://127.0.0.1"))
        result = await accessor.get(id=1)
        assert result.__dict__ == {"id": 1, "name": "cluster_1", "description": "cluster_1"}

        with suppress(ObjectDoesNotExistError):
            await accessor.get(id=4)

    async def test_get_or_none_single_object_success(self):
        accessor = ClusterNode("clusters", requester=MockRequester(base_url="http://127.0.0.1"))
        result = await accessor.get_or_none(id=1)
        assert result.__dict__ == {"id": 1, "name": "cluster_1", "description": "cluster_1"}

        result = await accessor.get_or_none(id=4)
        assert result is None

    async def test_list_success(self):
        accessor = ClusterNode("clusters", requester=MockRequester(base_url="http://127.0.0.1"))

        result = await accessor.list()
        assert len(result) == 3
        for i, item in enumerate(result):
            assert result[i].id == i + 1
            assert result[i].name == f"cluster_{i + 1}"

    async def test_all_success(self):
        accessor = ClusterNode(
            "clusters", requester=MockRequester(base_url="http://127.0.0.1"), query_params={"offset": 0, "limit": 1}
        )

        result = await accessor.all()
        assert len(result) == 3
        for i, item in enumerate(result):
            assert result[i].id == i + 1
            assert result[i].name == f"cluster_{i + 1}"
