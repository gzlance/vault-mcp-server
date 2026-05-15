"""Vault 知识库数据库封装（v2.0 Mixin 多重继承）。

使用方法与 v1.x 完全兼容:
    with VaultDB() as db:
        db.initialize()
        db.insert_note(...)
        db.list_todos("my-project")
"""

from db.base import ConnectionManager
from db.graph import GraphOperations
from db.notes import NotesOperations
from db.session import SessionOperations
from db.todos import TodosOperations
from db.wikilinks import WikilinkOperations


class VaultDB(
    ConnectionManager,
    NotesOperations,
    TodosOperations,
    SessionOperations,
    GraphOperations,
    WikilinkOperations,
):
    """Vault 知识库数据库封装。

    通过 Mixin 多重继承组合 6 个子模块的全部方法，
    对外接口与 v1.x 的单一 db.py VaultDB 完全兼容。
    """
