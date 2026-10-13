import pytest

from sponsorscope.http import Http


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
async def http():
    client = Http(sleep=_no_sleep)
    yield client
    await client.aclose()
