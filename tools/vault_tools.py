"""v2.0 向后兼容重导出。实际实现已拆分到独立文件。请直接导入对应模块。"""

from tools.vault_init import handle_init  # noqa: F401, E402
from tools.vault_list import handle_list  # noqa: F401, E402
from tools.vault_log import handle_log  # noqa: F401, E402
from tools.vault_orphan import handle_orphan  # noqa: F401, E402
from tools.vault_resume import handle_resume  # noqa: F401, E402
from tools.vault_save import handle_save  # noqa: F401, E402
from tools.vault_search import handle_search  # noqa: F401, E402
from tools.vault_stats import handle_stats  # noqa: F401, E402
from tools.vault_tags import handle_tags  # noqa: F401, E402
from tools.vault_update import handle_update  # noqa: F401, E402
