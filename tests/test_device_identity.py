"""Test the Device-Information-Service identity read in wamble.device_info.

The positive path (a device that exposes a model) needs hardware; the
no-information path is what must stay graceful, so it is pinned here: a device
without the Device Information Service yields an empty identity, not an error.
"""

from wamble.device_info import read_identity


class TestReadIdentity:
    async def test_device_without_dis_returns_empty(self, gatt_env):
        # The fake exposes a Battery service, not Device Information.
        assert await read_identity(gatt_env.client) == ""
