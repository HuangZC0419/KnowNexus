"""直接读取本地混合标注（LabelFast）项目目录并构建知识图谱。

目录约定（由混合标注服务保存）：

    <project_dir>/
      project.json                 项目元数据（id/name/labels/relation_types）
      files/<file_id>/
        meta.json                  文件元数据（id/name/source_type ...）
        annotations.json           text/spans/relations/paragraphs/figures
        blocks.json                sections/blocks（仅用于补充页码）
        markdown/result.md         结构化正文
        assets/...                 图表截图等资源

只为 annotations.json 中的文件（doc）、实体（spans）与图表（figures）建节点：

- 文件：``doc:<file_id>``，name=文件名去扩展名，label=``文件``；
  仅当该文件至少有一个有效实体或图表时才生成；
- 实体：``ent:<file_id>:<span_id>``，name=标注文本，label=标注标签；
- 图表：``fig:<file_id>:<figure_id>``，name=caption（缺失时依次回退
  资产文件名去扩展名、图表 id）；
- 归属边：每个实体/图表节点各生成一条 ``属于`` 边指向所属文件节点
  （``source=子节点``、``target=doc:<file_id>``、kind=relation、weight=1.0）；
- 实体关系：source/target 指向同一文件内的实体节点，kind=relation；
- 不生成章节/段落节点，也不生成其它层级边。

本模块只读文件系统，不访问网络、不导入 FastAPI / Pydantic，便于在
Python 3.7 运行时以纯函数方式测试。所有节点属性值统一为字符串，
以满足知识库 OntologyNode.attributes 的 ``[{key, value}]`` 契约。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services.jsonl_import import (
    DEFAULT_ENTITY_LABEL,
    DEFAULT_RELATION,
)

PROJECT_FILE = "project.json"
META_FILE = "meta.json"
ANNOTATIONS_FILE = "annotations.json"
BLOCKS_FILE = "blocks.json"

DOC_LABEL = "文件"
FIGURE_LABEL = "图"
TABLE_LABEL = "表"
BELONG_RELATION = "属于"
FIGURE_ASSET_RELATIVE_DIR = os.path.join("assets", "figures")
LOCAL_ORIGIN_PREFIX = "labelfast:"

# 单个 annotations.json / blocks.json 的读取上限：超限时跳过该 JSON 并
# 写入 summary.warnings，避免把超大文件读进内存。
MAX_LOCAL_JSON_BYTES = 50 * 1024 * 1024

MAX_WARNINGS = 100

_FILE_SEPARATOR_RE = re.compile(r"[\\/]")


class MixedLocalImportError(Exception):
    """本地混合标注项目读取/解析失败。

    ``kind`` 用于让路由层映射 HTTP 状态码：
    ``invalid``(路径非法)、``not_found``、``read``、``parse``、``too_large``。
    """

    def __init__(self, message: str, kind: str = "read"):
        super().__init__(message)
        self.kind = kind


@dataclass
class LocalGraphResult:
    """本地项目导入结果，供 main 直接落盘。"""

    project_id: str
    project_name: str
    nodes: List[dict] = field(default_factory=list)
    edges: List[dict] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 基础读取与规范化
# ============================================================

def _clean_text(value: str) -> str:
    """清除孤立代理字符等无法编码为 UTF-8 的内容。"""
    return value.encode("utf-8", "replace").decode("utf-8")


def _scalar_text(value) -> str:
    """只接受标量值，避免把 dict/list 强转成 repr。"""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return _clean_text(str(value)).strip()


def _string_items(value) -> List[str]:
    """把标签/关系类型数组规范化为非空字符串数组。"""
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, (int, float)):
            text = str(item)
        else:
            continue
        if text:
            result.append(_clean_text(text))
    return result


def _decode_bytes(raw: bytes) -> str:
    """按 BOM / UTF-8 / GB18030 顺序解码文本文件。"""
    if not raw:
        return ""
    encodings = []
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.extend(("utf-8-sig", "utf-8", "gb18030"))
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_text(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            return _decode_bytes(handle.read())
    except OSError as exc:
        raise MixedLocalImportError(
            "读取文件失败：%s（%s）" % (path, exc), kind="read"
        )


def normalize_local_dir(path: str) -> str:
    """校验并规范化用户填写的本地目录：必须是已存在的绝对路径。"""
    text = (path or "").strip()
    if not text:
        raise MixedLocalImportError("路径不能为空", kind="invalid")
    if not os.path.isabs(text):
        raise MixedLocalImportError(
            "路径必须是绝对路径（例如 C:\\data\\projects\\测试项目）",
            kind="invalid",
        )

    normalized = os.path.normpath(text)
    if not os.path.exists(normalized):
        raise MixedLocalImportError("路径不存在：%s" % normalized, kind="not_found")
    if not os.path.isdir(normalized):
        raise MixedLocalImportError("路径不是文件夹：%s" % normalized, kind="invalid")
    return normalized


def _project_file_path(project_dir: str) -> str:
    return os.path.join(project_dir, PROJECT_FILE)


def _load_project_meta(project_dir: str) -> dict:
    """严格读取 project.json；缺失时按「不是混合标注项目」处理。"""
    path = _project_file_path(project_dir)
    if not os.path.isfile(path):
        raise MixedLocalImportError(
            "目录不是混合标注项目（缺少 project.json）：%s" % project_dir,
            kind="not_found",
        )
    try:
        text = _read_text(path)
    except MixedLocalImportError as exc:
        raise MixedLocalImportError(
            "读取 project.json 失败：%s" % exc, kind="read"
        )
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise MixedLocalImportError(
            "project.json 不是有效 JSON：%s" % path, kind="parse"
        )
    if not isinstance(data, dict):
        raise MixedLocalImportError(
            "project.json 格式不正确：%s" % path, kind="parse"
        )
    return data


def _project_info(project_dir: str, meta: dict) -> dict:
    fallback_name = os.path.basename(project_dir.rstrip("\\/")) or "混合标注项目"
    return {
        "dir": project_dir,
        "id": _scalar_text(meta.get("id")) or fallback_name,
        "name": _scalar_text(meta.get("name")) or fallback_name,
        "labels": _string_items(meta.get("labels")),
        "relation_types": _string_items(meta.get("relation_types")),
    }


def load_project_info(project_dir: str) -> dict:
    """读取单个混合标注项目的摘要信息（只读），供扫描接口复用。"""
    normalized = normalize_local_dir(project_dir)
    return _project_info(normalized, _load_project_meta(normalized))


def _warn(warnings: List[str], message: str) -> None:
    if len(warnings) < MAX_WARNINGS:
        warnings.append(message)


def _load_optional_json(
    path: str,
    warnings: List[str],
    display_name: str,
    max_bytes: Optional[int] = None,
) -> Optional[Any]:
    """读取可选 JSON；缺失、超限或解析失败时返回 None 并记录告警。"""
    if not os.path.isfile(path):
        return None
    if max_bytes is not None:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size > max_bytes:
            megabytes = max(1, max_bytes // (1024 * 1024))
            _warn(
                warnings,
                "%s 超过 %d MB，已跳过" % (display_name, megabytes),
            )
            return None
    try:
        text = _read_text(path)
    except MixedLocalImportError as exc:
        _warn(warnings, "%s 读取失败，已跳过（%s）" % (display_name, exc))
        return None
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        _warn(warnings, "%s 不是有效 JSON，已跳过" % display_name)
        return None


# ============================================================
# 文件列表与项目扫描
# ============================================================

def _collect_file_entries(
    project_dir: str, warnings: List[str]
) -> List[dict]:
    """收集 files/* 文件目录，按 meta.name 稳定排序。

    只处理包含 meta.json 的目录；缺失或损坏的 meta.json 记录告警后跳过，
    以免单个损坏文件阻断整个项目导入。
    """
    files_dir = os.path.join(project_dir, "files")
    if not os.path.isdir(files_dir):
        return []

    try:
        child_names = sorted(os.listdir(files_dir))
    except OSError as exc:
        raise MixedLocalImportError(
            "读取 files 目录失败：%s（%s）" % (files_dir, exc), kind="read"
        )

    entries = []
    for child in child_names:
        dir_path = os.path.join(files_dir, child)
        if not os.path.isdir(dir_path):
            continue
        meta_path = os.path.join(dir_path, META_FILE)
        if not os.path.isfile(meta_path):
            _warn(warnings, "文件目录 %s 缺少 meta.json，已跳过" % child)
            continue
        meta = _load_optional_json(
            meta_path, warnings, "文件目录 %s 的 meta.json" % child
        )
        if not isinstance(meta, dict):
            continue
        file_id = _scalar_text(meta.get("id")) or child
        file_name = _scalar_text(meta.get("name")) or child
        entries.append({
            "dir": dir_path,
            "file_id": file_id,
            "file_name": file_name,
        })

    entries.sort(
        key=lambda item: (item["file_name"], item["file_id"], item["dir"])
    )
    return entries


def _scan_project(project_dir: str, meta: dict) -> dict:
    """为扫描接口构造单个项目摘要；告警不参与扫描响应。"""
    info = _project_info(project_dir, meta)
    entries = _collect_file_entries(project_dir, [])
    file_names = [entry["file_name"] for entry in entries]
    return {
        "dir": info["dir"],
        "name": info["name"],
        "labels": info["labels"],
        "relation_types": info["relation_types"],
        "file_count": len(entries),
        "file_names": file_names,
    }


def scan_local_projects(path: str) -> dict:
    """扫描单个项目目录或 projects 父目录，返回可导入项目列表。"""
    normalized = normalize_local_dir(path)
    single_project = os.path.isfile(_project_file_path(normalized))

    project_dirs = []
    if single_project:
        base_dir = os.path.dirname(normalized)
        project_dirs.append(normalized)
    else:
        base_dir = normalized
        try:
            child_names = sorted(os.listdir(normalized))
        except OSError as exc:
            raise MixedLocalImportError(
                "读取目录失败：%s（%s）" % (normalized, exc), kind="read"
            )
        for child in child_names:
            child_dir = os.path.join(normalized, child)
            if os.path.isdir(child_dir) and os.path.isfile(
                _project_file_path(child_dir)
            ):
                project_dirs.append(child_dir)

    projects = []
    for project_dir in project_dirs:
        try:
            meta = _load_project_meta(project_dir)
        except MixedLocalImportError:
            # 父目录扫描时跳过损坏/不可读的子项目，避免一项失败拖垮整个列表；
            # 用户直接指定单项目路径时仍把错误抛给上层。
            if single_project:
                raise
            continue
        projects.append(_scan_project(project_dir, meta))

    if not projects:
        raise MixedLocalImportError(
            "目录下没有找到混合标注项目（子目录需包含 project.json）：%s"
            % normalized,
            kind="not_found",
        )

    projects.sort(key=lambda item: (item["name"], item["dir"]))
    return {
        "path": normalized,
        "base_dir": base_dir,
        "projects": projects,
    }


# ============================================================
# 节点/边构造辅助
# ============================================================

def _attributes(pairs: Dict[str, Any]) -> List[dict]:
    result = []
    for key, value in pairs.items():
        if value is None:
            text = ""
        else:
            text = _clean_text(str(value))
        result.append({"key": str(key), "value": text})
    return result


def _make_node(
    node_id: str,
    name: str,
    label: str,
    attributes: Dict[str, Any],
    origin: str,
) -> dict:
    safe_label = _clean_text(str(label or "")).strip()
    safe_name = _clean_text(str(name or "")).strip()
    if not safe_name:
        safe_name = safe_label or node_id
    return {
        "id": node_id,
        "name": safe_name,
        "label": safe_label,
        "x": 0.0,
        "y": 0.0,
        "parent_id": None,
        "attributes": _attributes(attributes),
        "origin": origin,
    }


def _page_text(*values) -> str:
    """按优先级选取第一个可用的页码值，全部缺失时返回空字符串。"""
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return _clean_text(str(value))
        if isinstance(value, str):
            text = _clean_text(value).strip()
            if text:
                return text
    return ""


def _figure_asset_raw(figure: dict) -> str:
    return _scalar_text(figure.get("assetPath")) or _scalar_text(
        figure.get("asset_path")
    )


def _document_name(file_name: str, file_id: str) -> str:
    """文档节点显示名：文件名去扩展名；缺失时回退 file_id。"""
    base = _FILE_SEPARATOR_RE.split((file_name or "").strip())[-1]
    stem, _ = os.path.splitext(base)
    return (stem or base).strip() or file_id


def _figure_asset_stem(raw: str) -> str:
    """取资产路径的文件名（去扩展名），用于 caption 缺失时的显示名。"""
    if not raw:
        return ""
    base = _FILE_SEPARATOR_RE.split(raw.strip())[-1]
    stem, _ = os.path.splitext(base)
    return (stem or base).strip()


def _figure_asset_path(file_dir: str, figure: dict, figure_id: str) -> str:
    """返回图表资产的绝对路径；缺少 assetPath 时按图表 id 约定推导。"""
    raw = _figure_asset_raw(figure)
    if not raw:
        raw = os.path.join(FIGURE_ASSET_RELATIVE_DIR, "%s.png" % figure_id)
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.join(file_dir, raw))


def _figure_name(caption: str, asset_raw: str, figure_id: str) -> str:
    """显示名：caption -> 资产文件名（去扩展名）-> 图表 id。"""
    return caption or _figure_asset_stem(asset_raw) or figure_id


def _block_index(blocks: Any) -> Dict[str, dict]:
    if not isinstance(blocks, dict):
        return {}
    entries = blocks.get("blocks")
    if not isinstance(entries, list):
        return {}
    result = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        block_id = _scalar_text(item.get("id"))
        if block_id:
            result.setdefault(block_id, item)
    return result


def _span_text(span: dict, full_text: str) -> str:
    text = _scalar_text(span.get("text"))
    if text:
        return text
    try:
        start = int(span.get("start"))
        end = int(span.get("end"))
    except (TypeError, ValueError):
        return ""
    if full_text and 0 <= start < end <= len(full_text):
        return full_text[start:end]
    return ""


# ============================================================
# 图谱构建
# ============================================================

class _GraphBuilder:
    """按文件聚合节点与边，保持稳定的生成顺序。"""

    def __init__(self, project_id: str, project_name: str, project_dir: str):
        self.project_id = project_id
        self.project_name = project_name
        self.project_dir = project_dir
        self.nodes: List[dict] = []
        self.edges: List[dict] = []
        self.labels: Dict[str, int] = {}
        self.warnings: List[str] = []
        self._node_ids = set()
        self._edge_keys = set()
        self.files = _collect_file_entries(project_dir, self.warnings)

    # ---- 基础写操作 -------------------------------------------------

    def _add_node(self, node: dict) -> bool:
        node_id = node.get("id")
        if not node_id:
            return False
        if node_id in self._node_ids:
            _warn(self.warnings, "节点 id「%s」重复，已跳过" % node_id)
            return False
        self._node_ids.add(node_id)
        self.nodes.append(node)
        label = node.get("label") or DEFAULT_ENTITY_LABEL
        self.labels[label] = self.labels.get(label, 0) + 1
        return True

    def _add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        kind: str,
        origin: str,
    ) -> bool:
        if not source or not target or source == target:
            return False
        key = (source, target, relation)
        if key in self._edge_keys:
            return False
        self._edge_keys.add(key)
        self.edges.append({
            "id": str(uuid.uuid4()),
            "source": source,
            "target": target,
            "relation": relation,
            "kind": kind,
            "characteristics": [],
            "weight": None if kind in ("hierarchy", "parent-child") else 1.0,
            "origin": origin,
        })
        return True

    def _load_file_json(
        self, file_dir: str, file_name: str, json_name: str
    ) -> Optional[Any]:
        path = os.path.join(file_dir, json_name)
        return _load_optional_json(
            path,
            self.warnings,
            "文件「%s」的 %s" % (file_name, json_name),
            max_bytes=MAX_LOCAL_JSON_BYTES,
        )

    # ---- 单文件 -----------------------------------------------------

    def build_file(self, entry: dict) -> None:
        file_dir = entry["dir"]
        file_id = entry["file_id"]
        file_name = entry["file_name"]
        origin = LOCAL_ORIGIN_PREFIX + (file_name or file_id)

        annotations = self._load_file_json(
            file_dir, file_name, ANNOTATIONS_FILE
        )
        # 只从 annotations.json 取文件/实体/图表；没有该文件（或格式非法）
        # 的文件不产生任何节点与边，也不读取 blocks.json。
        if not isinstance(annotations, dict):
            return

        # blocks.json 仅用于给实体补充页码，不再生成章节/段落节点。
        blocks = self._load_file_json(file_dir, file_name, BLOCKS_FILE)
        block_map = _block_index(blocks)

        # 先收集有效子节点，避免为「只有非法/空标注」的文件生成文档节点。
        figure_nodes = self._collect_figure_nodes(
            file_dir, file_id, annotations, origin
        )
        entity_nodes, span_node_ids = self._collect_entity_nodes(
            file_id,
            file_name,
            annotations,
            block_map,
            origin,
        )
        child_nodes = figure_nodes + entity_nodes
        if not child_nodes:
            return

        # 文档节点：按 file_id 保证唯一，name 允许跨文件同名。
        doc_id = "doc:%s" % file_id
        self._add_node(_make_node(
            doc_id,
            _document_name(file_name, file_id),
            DOC_LABEL,
            {
                "file_name": file_name,
            },
            origin,
        ))

        # 归属边方向固定为「子节点 -> 文档节点」，weight 由 _add_edge
        # 对 kind=relation 统一写为 1.0。
        for node in child_nodes:
            if self._add_node(node):
                self._add_edge(
                    node["id"], doc_id, BELONG_RELATION, "relation", origin
                )

        self._build_relations(annotations, span_node_ids, origin)

    def _collect_figure_nodes(
        self,
        file_dir: str,
        file_id: str,
        annotations: Any,
        origin: str,
    ) -> List[dict]:
        if not isinstance(annotations, dict):
            return []
        raw_figures = annotations.get("figures")
        if not isinstance(raw_figures, list):
            return []

        nodes = []
        for raw in raw_figures:
            if not isinstance(raw, dict):
                continue
            figure_id = _scalar_text(raw.get("id")) or _scalar_text(
                raw.get("figure_id")
            )
            if not figure_id:
                _warn(self.warnings, "图表缺少 id，已跳过")
                continue
            kind = _scalar_text(raw.get("kind")).lower()
            label = TABLE_LABEL if kind == "table" else FIGURE_LABEL
            caption = _scalar_text(raw.get("caption"))
            asset_raw = _figure_asset_raw(raw)
            node_id = "fig:%s:%s" % (file_id, figure_id)
            nodes.append(_make_node(
                node_id,
                _figure_name(caption, asset_raw, figure_id),
                label,
                {
                    "asset_path": _figure_asset_path(
                        file_dir, raw, figure_id
                    ),
                    "page": _page_text(raw.get("page")),
                    "kind": kind,
                },
                origin,
            ))
        return nodes

    def _collect_entity_nodes(
        self,
        file_id: str,
        file_name: str,
        annotations: Any,
        block_map: Dict[str, dict],
        origin: str,
    ) -> Tuple[List[dict], Dict[str, str]]:
        if not isinstance(annotations, dict):
            return [], {}
        raw_spans = annotations.get("spans")
        if not isinstance(raw_spans, list):
            return [], {}

        full_text = annotations.get("text")
        if not isinstance(full_text, str):
            full_text = ""

        nodes = []
        span_node_ids = {}
        for raw in raw_spans:
            if not isinstance(raw, dict):
                continue
            span_id = _scalar_text(raw.get("id")) or _scalar_text(
                raw.get("span_id")
            )
            if not span_id:
                _warn(self.warnings, "实体标注缺少 id，已跳过")
                continue
            text = _span_text(raw, full_text)
            label = _scalar_text(raw.get("label")) or DEFAULT_ENTITY_LABEL
            block_id = _scalar_text(raw.get("blockId")) or _scalar_text(
                raw.get("block_id")
            )
            block = block_map.get(block_id, {}) if block_id else {}
            node_id = "ent:%s:%s" % (file_id, span_id)
            nodes.append(_make_node(
                node_id,
                text or label or span_id,
                label,
                {
                    "source_file": file_name,
                    "page": _page_text(block.get("page"), raw.get("page")),
                },
                origin,
            ))
            span_node_ids.setdefault(span_id, node_id)
        return nodes, span_node_ids

    def _build_relations(
        self,
        annotations: Any,
        span_node_ids: Dict[str, str],
        origin: str,
    ) -> None:
        if not isinstance(annotations, dict):
            return
        raw_relations = annotations.get("relations")
        if not isinstance(raw_relations, list):
            return

        for raw in raw_relations:
            if not isinstance(raw, dict):
                continue
            from_id = (
                _scalar_text(raw.get("fromId"))
                or _scalar_text(raw.get("from_id"))
                or _scalar_text(raw.get("from"))
                or _scalar_text(raw.get("source"))
            )
            to_id = (
                _scalar_text(raw.get("toId"))
                or _scalar_text(raw.get("to_id"))
                or _scalar_text(raw.get("to"))
                or _scalar_text(raw.get("target"))
            )
            source = span_node_ids.get(from_id)
            target = span_node_ids.get(to_id)
            if not source or not target:
                _warn(
                    self.warnings,
                    "关系端点无法匹配，已跳过（%s → %s）" % (from_id, to_id),
                )
                continue
            relation = (
                _scalar_text(raw.get("type"))
                or _scalar_text(raw.get("relation"))
                or DEFAULT_RELATION
            )
            self._add_edge(source, target, relation, "relation", origin)

    # ---- 汇总 -------------------------------------------------------

    def summary(self) -> dict:
        labels = dict(
            sorted(
                self.labels.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        )
        return {
            "records": len(self.nodes) + len(self.edges),
            "files": len(self.files),
            "entities": len(self.nodes),
            "relations": len(self.edges),
            "labels": labels,
            "file_names": [entry["file_name"] for entry in self.files],
            "warnings": list(self.warnings),
        }


def build_local_graph(project_dir: str) -> LocalGraphResult:
    """读取本地混合标注项目目录并生成知识图谱。

    返回的节点尚未布局；main 会复用 ``prepare_imported_nodes`` 完成
    分列布局与 parent_id 注入（本模块只产生 kind=relation 的边，因此
    不会注入 parent_id）。所有文件都没有有效实体/图表时返回空节点列表，
    由上层按「图谱为空」返回 502，避免创建空知识库项目。
    """
    normalized = normalize_local_dir(project_dir)
    meta = _load_project_meta(normalized)
    info = _project_info(normalized, meta)
    builder = _GraphBuilder(info["id"], info["name"], normalized)
    for entry in builder.files:
        builder.build_file(entry)

    return LocalGraphResult(
        project_id=info["id"],
        project_name=info["name"],
        nodes=builder.nodes,
        edges=builder.edges,
        summary=builder.summary(),
    )
