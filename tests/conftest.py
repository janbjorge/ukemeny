"""Guards for every test: no Jev tokens and no network. Use fakes or httpx2.MockTransport."""

import os
import socket
from collections.abc import Iterator
from typing import NoReturn

import pytest

# The site configures Logfire when adapters.web.main is imported, before any fixture runs: without a token it sends nothing
os.environ.pop("LOGFIRE_TOKEN", None)


class NetworkUsedError(RuntimeError):
    pass


def _blocked(*args: object, **kwargs: object) -> NoReturn:
    raise NetworkUsedError("Tests must not use the network or Jev. Use a fake or httpx2.MockTransport instead.")


@pytest.fixture(autouse=True)
def _no_jev_and_no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    real_connect = socket.socket.connect

    def connect(self: socket.socket, address: socket._Address) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _blocked()
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    yield
