"""Direct iCloud IMAP provider tests with no network access."""
from unittest.mock import MagicMock

import pytest

import src.warden.mail.icloud as icloud_mod


@pytest.fixture(autouse=True)
def reset_imap_factory():
    icloud_mod.set_imap_factory(None)
    yield
    icloud_mod.set_imap_factory(None)


def test_search_with_no_matches_returns_empty_list():
    fake = MagicMock()
    fake.login.return_value = ("OK", [b"Logged in"])
    fake.select.return_value = ("OK", [b"0"])
    fake.search.return_value = ("OK", [None])
    fake.logout.return_value = ("BYE", [])
    icloud_mod.set_imap_factory(lambda _host, _port: fake)

    provider = icloud_mod.ICloudMailProvider(
        "user@icloud.com", "app-password", "icloud-test"
    )

    assert provider.search("no-such-message", limit=1) == []
    fake.fetch.assert_not_called()
    fake.logout.assert_called_once()
