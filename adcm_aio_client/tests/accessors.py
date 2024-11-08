import unittest
from unittest.mock import AsyncMock, patch

from adcm_aio_client.core.accessors import NonPaginatedAccessor, Filter
from adcm_aio_client.core.exceptions import (
    ObjectDoesNotExistError,
    MultipleObjectsReturnedError,
    MissingParameterException,
    InvalidArgumentError,
)
from adcm_aio_client.core.objects import Cluster, ClusterNode
from adcm_aio_client.core.requesters import Requester


class TestNonPaginatedAccessor(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.accessor = ClusterNode("clusters", requester=AsyncMock())
        self.api_request = AsyncMock()

    async def test_get_single_object_success(self):
        # Simulate API response for a single object
        self.api_request.return_value = {"results": [{"id": 1, "name": "cluster_1"}]}

        # Call the get method
        result = await self.accessor.get(id=1)

        # Assert response
        self.assertEqual(result, {"id": 1, "name": "cluster_1"})

    async def test_get_no_objects_found(self):
        # Simulate an API response indicating no objects found
        self.api_request.return_value = {"results": []}

        with self.assertRaises(ObjectDoesNotExistError):
            await self.accessor.get(id=2)

    async def test_get_multiple_objects_found(self):
        # Simulate an API response with multiple objects
        self.api_request.return_value = {"results": [{"id": 1, "name": "cluster_1"}, {"id": 2, "name": "cluster_2"}]}

        with self.assertRaises(MultipleObjectsReturnedError):
            await self.accessor.get(Filter({"id": 1}))

    async def test_get_invalid_filter(self):
        # Pass an invalid filter to the get method
        with self.assertRaises(MissingParameterException):
            await self.accessor.get(None)

    async def test_get_invalid_argument(self):
        # Simulate an API response for an invalid argument scenario
        with self.assertRaises(InvalidArgumentError):
            await self.accessor.get(Filter({"invalid_key": 999}))


if __name__ == "__main__":
    unittest.main()
