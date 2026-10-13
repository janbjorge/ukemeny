import os

import httpx2
import pytest

from tests.conftest import NetworkUsedError


async def test_tests_cannot_reach_the_network_or_jev() -> None:
    assert "TYPESAFE_API_KEY" not in os.environ
    async with httpx2.AsyncClient() as client:
        with pytest.raises(Exception) as caught:
            await client.get("https://api.typesafe.ai/v1/models")
    if isinstance(caught.value, ExceptionGroup):
        assert caught.group_contains(NetworkUsedError)
    else:
        assert isinstance(caught.value, (NetworkUsedError, httpx2.HTTPError))
