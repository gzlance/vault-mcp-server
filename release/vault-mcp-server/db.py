"""向后兼容重导出。v2.0 实际实现已拆分到 db/ 子模块。请使用 from db import VaultDB。"""

from db import VaultDB  # noqa: F401, E402
