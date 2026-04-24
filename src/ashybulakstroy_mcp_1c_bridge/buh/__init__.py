"""Business accounting integration layer for 1C Kazakhstan."""

from .client import BuhClient, ConnectionMode, OneCUnifiedClient
from .inspect import BuhInspector, OneCInspector
from .odata import BuhODataClient, OneCODataClient
from .rpc import BuhError, BuhRpcClient, OneCClient, OneCError

__all__ = [
    "BuhClient",
    "ConnectionMode",
    "BuhInspector",
    "BuhODataClient",
    "BuhRpcClient",
    "BuhError",
    # compatibility aliases
    "OneCUnifiedClient",
    "OneCInspector",
    "OneCODataClient",
    "OneCClient",
    "OneCError",
]
