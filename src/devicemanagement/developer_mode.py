"""Read Developer Mode without inferring it from unrelated service errors."""
import asyncio


async def read_developer_mode(lockdown):
    value = await asyncio.wait_for(lockdown.get_value(
        domain="com.apple.security.mac.amfi", key="DeveloperModeStatus"), timeout=5)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return None

