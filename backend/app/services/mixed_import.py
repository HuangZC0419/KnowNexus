"""混合标注（LabelFast）导入的通用辅助逻辑。

职责边界：
- 自动分层布局；
- 把「包含」类 hierarchy 边转换为节点的 parent_id；
- 生成不重名的知识库项目名称。

本模块不访问网络、不读写知识库项目文件，也不导入 FastAPI / Pydantic，
便于在 Python 3.7 运行时做纯函数测试。

历史背景：早期版本通过混合标注服务端口拉取 graph.jsonl，现已改为
由 ``mixed_local_import`` 直接读取本地项目目录；端口拉取、地址校验、
远端响应大小限制等代码已下线，布局与命名规则保持不变。
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

from app.services.jsonl_import import CONTAIN_RELATION

# 布局常量：列宽/行高与前端节点卡片尺寸相匹配。
# 每列 16 行是为了容纳大型规范文档（单文件可达 200+ 章节），
# 避免章节数过多时横向铺开成过宽的画布。
LAYOUT_START_X = 40.0
LAYOUT_START_Y = 40.0
LAYOUT_COLUMN_WIDTH = 280.0
LAYOUT_ROW_HEIGHT = 120.0
LAYOUT_ROWS_PER_COLUMN = 16

# id 前缀 -> 基础列。未知前缀统一归入实体列。
_LAYOUT_COLUMN_BY_PREFIX = (
    ("doc:", 0),
    ("sec:", 1),
    ("par:", 2),
    ("fig:", 3),
    ("ent:", 4),
)
_ENTITY_COLUMN = 4
_COLUMN_COUNT = 5
_GRAPH_ID_PREFIX = "lf:"

_HIERARCHY_KINDS = ("parent-child", "hierarchy")


def node_layout_column(node_id: str) -> int:
    """根据节点 id 前缀返回基础列号；未知前缀归入实体列。"""
    raw = (node_id or "").strip()
    if raw.startswith(_GRAPH_ID_PREFIX):
        raw = raw[len(_GRAPH_ID_PREFIX):]
    for prefix, column in _LAYOUT_COLUMN_BY_PREFIX:
        if raw.startswith(prefix):
            return column
    return _ENTITY_COLUMN


def layout_nodes(nodes: Sequence[dict]) -> List[dict]:
    """按节点类型分列布局，返回新的节点列表（不修改入参）。

    规则：
    - doc/sec/par/fig/ent 分别从第 0~4 列起步；
    - 每列最多 LAYOUT_ROWS_PER_COLUMN 行，超出后换到右侧子列（x 增加一个列宽）；
    - 前一类型溢出占用后续列时，后续类型整体右移，
      从而保证任意两个节点坐标不重叠。
    """
    positioned = [dict(node) for node in nodes]
    groups = [[] for _ in range(_COLUMN_COUNT)]
    for node in positioned:
        column = node_layout_column(str(node.get("id", "")))
        groups[column].append(node)

    next_column = 0
    for column in range(_COLUMN_COUNT):
        group = groups[column]
        base_column = max(column, next_column)
        if group:
            used_columns = (
                len(group) + LAYOUT_ROWS_PER_COLUMN - 1
            ) // LAYOUT_ROWS_PER_COLUMN
            next_column = base_column + used_columns
        for index, node in enumerate(group):
            node["x"] = (
                LAYOUT_START_X
                + (base_column + index // LAYOUT_ROWS_PER_COLUMN)
                * LAYOUT_COLUMN_WIDTH
            )
            node["y"] = (
                LAYOUT_START_Y
                + (index % LAYOUT_ROWS_PER_COLUMN) * LAYOUT_ROW_HEIGHT
            )
    return positioned


def assign_parent_ids(
    nodes: Sequence[dict], edges: Sequence[dict]
) -> List[dict]:
    """按「包含」层级的 hierarchy / parent-child 边设置 target 的 parent_id。

    source 为父节点，target 为子节点；已有 parent_id 时保留第一个，
    不覆盖导出数据中原有的父子关系。

    语义过滤：只有 relation 为「包含」的层级边才代表真正的父子结构。
    「出现在」等其它关系即使被导出为 hierarchy 边，也只保留边本身，
    不注入 parent_id；source 不在节点集合中的悬空边同样跳过，
    避免产生指向不存在节点的 parent_id。
    """
    positioned = [dict(node) for node in nodes]
    node_map = {
        node.get("id"): node for node in positioned if node.get("id")
    }

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("kind") not in _HIERARCHY_KINDS:
            continue
        if edge.get("relation") != CONTAIN_RELATION:
            continue
        source_id = edge.get("source")
        target_id = edge.get("target")
        if not source_id or source_id == target_id:
            continue
        if source_id not in node_map:
            continue
        target = node_map.get(target_id)
        if target is None or target.get("parent_id"):
            continue
        target["parent_id"] = source_id
    return positioned


def prepare_imported_nodes(
    nodes: Sequence[dict], edges: Sequence[dict]
) -> List[dict]:
    """完成布局与 parent_id 注入，返回可直接落盘的节点列表。"""
    return assign_parent_ids(layout_nodes(nodes), edges)


# ============================================================
# 项目命名
# ============================================================

def unique_project_name(
    name: str,
    existing_names: Iterable[str],
    max_length: int = 100,
) -> str:
    """生成不与现有项目重名的名称：``名称 (2)``、``名称 (3)`` ...

    结果长度不超过 ``max_length``（知识库项目名校验上限）。
    """
    base = (name or "").strip() or "混合标注项目"
    if len(base) > max_length:
        base = base[:max_length]

    used = {str(item) for item in (existing_names or [])}
    if base not in used:
        return base

    suffix_index = 2
    while True:
        suffix = " (%d)" % suffix_index
        stem = base[: max(1, max_length - len(suffix))]
        candidate = stem + suffix
        if candidate not in used:
            return candidate
        suffix_index += 1
