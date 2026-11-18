"""本地混合标注项目扫描与导入测试。

覆盖：
- 纯函数：布局分列、parent_id 注入、重名后缀；
- 本地目录解析：project.json / meta.json / annotations.json / blocks.json
  的扁平图谱映射（doc / ent / fig 三类节点 + 子节点指向文档的「属于」边）；
- POST /api/mixed/scan-local：单项目、父目录、跳过无 project.json 的目录、
  路径错误；
- POST /api/mixed/import-local：节点/边数量与 id、origin 分文件、扁平结构、
  空项目 502、重名后缀、规模上限与落盘回滚；
- perspective 的 labelfast -> jsonl 来源映射。

所有 HTTP 用例使用临时目录替换 PROJECTS_DIR / INDEX_FILE，不触碰真实数据。
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main as main_module
from app.routers import perspective as perspective_module
from app.routers.perspective import _normalize_source_type, _parse_origin
from app.services import mixed_local_import
from app.services.mixed_import import (
    assign_parent_ids,
    layout_nodes,
    unique_project_name,
)
from app.services.mixed_local_import import build_local_graph, scan_local_projects


# ============================================================
# 测试夹具
# ============================================================

PROJECT_ID = "p1"


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _write_file_spec(project_dir, spec):
    file_id = spec["file_id"]
    file_dir = Path(project_dir) / "files" / file_id
    file_dir.mkdir(parents=True, exist_ok=True)
    _write_json(file_dir / "meta.json", {
        "id": file_id,
        "project_id": PROJECT_ID,
        "name": spec["name"],
        "source_type": "pdf",
        "source_ext": "pdf",
    })
    if "blocks" in spec:
        _write_json(file_dir / "blocks.json", spec["blocks"])
    if "annotations" in spec:
        _write_json(file_dir / "annotations.json", spec["annotations"])
    if "markdown" in spec:
        markdown_path = file_dir / "markdown" / "result.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(spec["markdown"], encoding="utf-8")


def make_project(
    root,
    dir_name="项目A",
    name="测试项目",
    project_id=PROJECT_ID,
    labels=None,
    relation_types=None,
    files=None,
):
    project_dir = Path(root) / dir_name
    project_dir.mkdir(parents=True, exist_ok=True)
    _write_json(project_dir / "project.json", {
        "id": project_id,
        "name": name,
        "labels": labels or ["材料", "设备"],
        "relation_types": relation_types or ["ref"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    for spec in files or []:
        _write_file_spec(project_dir, spec)
    return project_dir


def file_a_spec():
    """有 blocks.json / annotations.json 的文件。"""
    return {
        "file_id": "f1",
        "name": "A标准.pdf",
        "blocks": {
            "version": 1,
            "sections": [
                {
                    "id": "s0001",
                    "number": "1",
                    "title": "1 范围",
                    "start": 0,
                    "end": 10,
                    "page": 1,
                },
                {
                    "id": "s0002",
                    "number": "2",
                    "title": "术语",
                    "start": 10,
                    "end": 20,
                    "page": 2,
                },
            ],
            "blocks": [
                {
                    "id": "b0001",
                    "text": "铜及铜合金拉制棒适用于一般用途。",
                    "page": 1,
                    "sectionId": "s0001",
                    "sectionNumber": "1",
                    "sectionTitle": "1 范围",
                },
                {
                    "id": "b0002",
                    "text": "未被段落标注的块。",
                    "page": 2,
                    "sectionId": "s0002",
                    "sectionNumber": "2",
                    "sectionTitle": "术语",
                },
            ],
        },
        "annotations": {
            "text": "铜及铜合金拉制棒适用于一般用途。",
            "spans": [
                {
                    "id": 1,
                    "start": 0,
                    "end": 3,
                    "label": "材料",
                    "text": "铜及铜",
                    "blockId": "b0001",
                },
                {
                    "id": 2,
                    "start": 13,
                    "end": 16,
                    "label": "用途",
                    "text": "用途。",
                    "blockId": "b0001",
                },
            ],
            "relations": [
                {"fromId": 1, "toId": 2, "type": "ref"},
            ],
            "paragraphs": [
                {"blockId": "b0001", "label": "定义", "note": "重点段落"},
            ],
            "figures": [
                {
                    "id": "tbl_0001",
                    "kind": "table",
                    "caption": "表1 化学成分",
                    "note": "",
                    "page": 1,
                    "bbox": [36.93, 101.17, 555.89, 705.03],
                    "assetPath": "assets/figures/tbl_0001.png",
                }
            ],
        },
    }


def file_b_spec():
    """无 blocks.json，由 markdown 标题粗切章节。"""
    return {
        "file_id": "f2",
        "name": "B标准.pdf",
        "markdown": "# 总则\n正文\n## 安装要求\n正文",
        "annotations": {
            "text": "设备安装应符合要求。",
            "spans": [
                {
                    "id": 1,
                    "start": 0,
                    "end": 2,
                    "label": "设备",
                    "text": "设备",
                    "blockId": "",
                }
            ],
            "relations": [],
            "paragraphs": [],
            "figures": [
                {
                    "id": "fig_0001",
                    "kind": "figure",
                    "caption": "",
                    "note": "",
                    "page": 3,
                    "bbox": [0, 0, 10, 20],
                    "assetPath": "assets/figures/fig_0001.png",
                }
            ],
        },
    }


def make_rich_project(root, dir_name="项目A", name="测试项目"):
    # 故意先写 B 再写 A，验证导入仍按 meta.name 稳定排序。
    return make_project(
        root,
        dir_name=dir_name,
        name=name,
        files=[file_b_spec(), file_a_spec()],
    )


# ============================================================
# 纯函数测试
# ============================================================

class LayoutTests(unittest.TestCase):
    def test_five_node_types_use_expected_base_columns(self):
        nodes = [
            {"id": "doc:a"},
            {"id": "sec:b"},
            {"id": "par:c"},
            {"id": "fig:d"},
            {"id": "ent:e"},
            {"id": "unknown:x"},
        ]
        positioned = layout_nodes(nodes)
        by_id = {node["id"]: node for node in positioned}

        expected_x = {
            "doc:a": 40,
            "sec:b": 320,
            "par:c": 600,
            "fig:d": 880,
            "ent:e": 1160,
        }
        for node_id, x in expected_x.items():
            self.assertEqual(by_id[node_id]["x"], x)
            self.assertEqual(by_id[node_id]["y"], 40)

        # 未知前缀归入实体列，占据同列下一行
        self.assertEqual(by_id["unknown:x"]["x"], by_id["ent:e"]["x"])
        self.assertNotEqual(by_id["unknown:x"]["y"], by_id["ent:e"]["y"])
        # 纯函数不修改入参
        self.assertNotIn("x", nodes[0])

    def test_parent_id_uses_first_contain_hierarchy_edge(self):
        nodes = [
            {"id": "doc:1"},
            {"id": "sec:1"},
            {"id": "sec:2", "parent_id": "doc:0"},
        ]
        edges = [
            {
                "kind": "hierarchy",
                "source": "doc:1",
                "target": "sec:1",
                "relation": "包含",
            },
            {
                "kind": "hierarchy",
                "source": "doc:1",
                "target": "sec:2",
                "relation": "包含",
            },
            {
                "kind": "relation",
                "source": "sec:1",
                "target": "sec:2",
                "relation": "出现在",
            },
        ]
        positioned = assign_parent_ids(nodes, edges)
        by_id = {node["id"]: node for node in positioned}
        self.assertEqual(by_id["sec:1"]["parent_id"], "doc:1")
        # 已有父节点时保留第一个
        self.assertEqual(by_id["sec:2"]["parent_id"], "doc:0")
        # 纯函数不修改入参
        self.assertNotIn("parent_id", nodes[1])

    def test_non_contain_hierarchy_edge_does_not_set_parent_id(self):
        nodes = [{"id": "ent:1"}, {"id": "par:1"}]
        edges = [
            {
                "kind": "hierarchy",
                "source": "ent:1",
                "target": "par:1",
                "relation": "出现在",
            }
        ]
        by_id = {node["id"]: node for node in assign_parent_ids(nodes, edges)}
        self.assertIsNone(by_id["par:1"].get("parent_id"))

    def test_dangling_hierarchy_source_does_not_set_parent_id(self):
        nodes = [{"id": "sec:1"}]
        edges = [
            {
                "kind": "hierarchy",
                "source": "doc:missing",
                "target": "sec:1",
                "relation": "包含",
            }
        ]
        by_id = {node["id"]: node for node in assign_parent_ids(nodes, edges)}
        self.assertIsNone(by_id["sec:1"].get("parent_id"))

    def test_unique_project_name_appends_suffix(self):
        self.assertEqual(unique_project_name("项目", []), "项目")
        self.assertEqual(unique_project_name("项目", {"项目"}), "项目 (2)")
        self.assertEqual(
            unique_project_name("项目", {"项目", "项目 (2)"}), "项目 (3)"
        )


# ============================================================
# 本地解析（纯函数）
# ============================================================

class LocalGraphBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kb-local-parse-")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)

    def test_nodes_edges_ids_and_origin_per_file(self):
        project_dir = make_rich_project(self.temp_dir)
        result = build_local_graph(str(project_dir))

        self.assertEqual(result.project_id, PROJECT_ID)
        self.assertEqual(result.project_name, "测试项目")

        by_id = {node["id"]: node for node in result.nodes}
        expected_ids = {
            "doc:f1",
            "fig:f1:tbl_0001",
            "ent:f1:1",
            "ent:f1:2",
            "doc:f2",
            "fig:f2:fig_0001",
            "ent:f2:1",
        }
        self.assertEqual(set(by_id), expected_ids)

        # 节点数 = 文档数 + 实体数 + 图表数；边数 = 实体数 + 图表数 + 实体关系数
        doc_ids = [
            node["id"] for node in result.nodes if node["label"] == "文件"
        ]
        entity_ids = [
            node_id for node_id in by_id if node_id.startswith("ent:")
        ]
        figure_ids = [
            node_id for node_id in by_id if node_id.startswith("fig:")
        ]
        self.assertEqual(len(doc_ids), 2)
        self.assertEqual(len(entity_ids), 3)
        self.assertEqual(len(figure_ids), 2)
        self.assertEqual(
            len(result.nodes), len(doc_ids) + len(entity_ids) + len(figure_ids)
        )
        # 实体关系只有 f1 的 1 条，其余边都是「属于」归属边
        self.assertEqual(len(result.edges), 2 + 3 + 1)

        # 文件按 meta.name 排序：A 在 B 之前
        self.assertEqual(doc_ids, ["doc:f1", "doc:f2"])

        # 只有 doc/ent/fig 三类节点，不生成章节/段落节点
        for node_id in by_id:
            self.assertTrue(
                node_id.startswith(("doc:", "ent:", "fig:")),
                node_id,
            )

        for node_id, node in by_id.items():
            expected_origin = (
                "labelfast:A标准.pdf"
                if ":f1" in node_id or node_id.endswith(":f1")
                else "labelfast:B标准.pdf"
            )
            self.assertEqual(node["origin"], expected_origin, node_id)

        for edge in result.edges:
            expected_origin = (
                "labelfast:A标准.pdf"
                if ":f1" in edge["source"]
                else "labelfast:B标准.pdf"
            )
            self.assertEqual(edge["origin"], expected_origin)

        # 文档节点核心字段
        self.assertEqual(by_id["doc:f1"]["name"], "A标准")
        self.assertEqual(by_id["doc:f1"]["label"], "文件")
        doc_attrs = {
            item["key"]: item["value"]
            for item in by_id["doc:f1"]["attributes"]
        }
        self.assertEqual(doc_attrs["file_name"], "A标准.pdf")
        self.assertNotIn("file_id", doc_attrs)
        self.assertEqual(by_id["doc:f2"]["name"], "B标准")
        f2_doc_attrs = {
            item["key"]: item["value"]
            for item in by_id["doc:f2"]["attributes"]
        }
        self.assertEqual(f2_doc_attrs["file_name"], "B标准.pdf")

        # 图表节点：caption / 资产文件名回退、绝对 asset_path
        self.assertEqual(by_id["fig:f1:tbl_0001"]["label"], "表")
        self.assertEqual(by_id["fig:f1:tbl_0001"]["name"], "表1 化学成分")
        self.assertEqual(by_id["fig:f2:fig_0001"]["label"], "图")
        # caption 为空时回退资产文件名（去扩展名）
        self.assertEqual(by_id["fig:f2:fig_0001"]["name"], "fig_0001")
        fig_attrs = {
            item["key"]: item["value"]
            for item in by_id["fig:f1:tbl_0001"]["attributes"]
        }
        self.assertTrue(os.path.isabs(fig_attrs["asset_path"]))
        self.assertTrue(fig_attrs["asset_path"].endswith(
            ("assets\\figures\\tbl_0001.png", "assets/figures/tbl_0001.png")
        ))
        self.assertEqual(fig_attrs["page"], "1")
        self.assertEqual(fig_attrs["kind"], "table")

        # 实体节点仍保留精简属性
        ent_attrs = {
            item["key"]: item["value"]
            for item in by_id["ent:f1:2"]["attributes"]
        }
        self.assertEqual(ent_attrs["source_file"], "A标准.pdf")
        self.assertNotIn("span_id", ent_attrs)
        self.assertNotIn("block_id", ent_attrs)
        self.assertEqual(ent_attrs["page"], "1")

        # 每个实体/图表各有一条「子节点 -> 文档节点」的属于边
        ownership_edges = {
            edge["source"]: edge
            for edge in result.edges
            if edge["relation"] == "属于"
        }
        expected_targets = {
            "fig:f1:tbl_0001": "doc:f1",
            "ent:f1:1": "doc:f1",
            "ent:f1:2": "doc:f1",
            "fig:f2:fig_0001": "doc:f2",
            "ent:f2:1": "doc:f2",
        }
        self.assertEqual(set(ownership_edges), set(expected_targets))
        for source_id, target_id in expected_targets.items():
            edge = ownership_edges[source_id]
            self.assertEqual(edge["target"], target_id)
            self.assertEqual(edge["kind"], "relation")
            self.assertEqual(edge["weight"], 1.0)

        # 实体之间的关系继续保留
        edge_keys = {
            (edge["source"], edge["target"], edge["relation"], edge["kind"])
            for edge in result.edges
        }
        self.assertIn(("ent:f1:1", "ent:f1:2", "ref", "relation"), edge_keys)

        summary = result.summary
        self.assertEqual(summary["records"], len(result.nodes) + len(result.edges))
        self.assertEqual(summary["files"], 2)
        self.assertEqual(summary["entities"], len(result.nodes))
        self.assertEqual(summary["relations"], len(result.edges))
        self.assertEqual(summary["file_names"], ["A标准.pdf", "B标准.pdf"])
        self.assertEqual(summary["labels"]["文件"], 2)
        self.assertEqual(summary["labels"]["表"], 1)
        self.assertEqual(summary["labels"]["图"], 1)
        self.assertEqual(summary["warnings"], [])

    def test_file_without_blocks_builds_flat_graph(self):
        project_dir = make_project(
            self.temp_dir, files=[file_b_spec()]
        )
        result = build_local_graph(str(project_dir))
        by_id = {node["id"]: node for node in result.nodes}

        self.assertEqual(set(by_id), {"doc:f2", "fig:f2:fig_0001", "ent:f2:1"})
        self.assertEqual(len(result.edges), 2)
        for edge in result.edges:
            self.assertEqual(edge["relation"], "属于")

    def test_figure_name_falls_back_to_id(self):
        spec = file_b_spec()
        spec["annotations"]["figures"] = [{
            "id": "fig_0002",
            "kind": "figure",
            "caption": "",
            "assetPath": "",
        }]
        project_dir = make_project(self.temp_dir, files=[spec])
        result = build_local_graph(str(project_dir))
        by_id = {node["id"]: node for node in result.nodes}
        self.assertEqual(by_id["fig:f2:fig_0002"]["name"], "fig_0002")

    def test_same_file_name_keeps_unique_doc_ids(self):
        spec_a = file_b_spec()
        spec_a["file_id"] = "f1"
        spec_a["name"] = "同名.pdf"
        spec_b = file_b_spec()
        spec_b["file_id"] = "f2"
        spec_b["name"] = "同名.pdf"
        project_dir = make_project(self.temp_dir, files=[spec_a, spec_b])
        result = build_local_graph(str(project_dir))
        by_id = {node["id"]: node for node in result.nodes}

        self.assertEqual(by_id["doc:f1"]["name"], "同名")
        self.assertEqual(by_id["doc:f2"]["name"], "同名")
        self.assertIn("doc:f1", by_id)
        self.assertIn("doc:f2", by_id)

    def test_no_annotations_generates_no_nodes_or_edges(self):
        spec = file_a_spec()
        del spec["annotations"]
        project_dir = make_project(self.temp_dir, files=[spec])
        result = build_local_graph(str(project_dir))

        self.assertEqual(result.nodes, [])
        self.assertEqual(result.edges, [])
        self.assertEqual(result.summary["files"], 1)
        self.assertEqual(result.summary["entities"], 0)
        self.assertEqual(result.summary["relations"], 0)

    def test_annotations_without_entities_or_figures_creates_no_doc(self):
        spec = file_a_spec()
        spec["annotations"] = {
            "text": "",
            "spans": [],
            "relations": [],
            "figures": [],
        }
        project_dir = make_project(self.temp_dir, files=[spec])
        result = build_local_graph(str(project_dir))

        self.assertEqual(result.nodes, [])
        self.assertEqual(result.edges, [])

    def test_oversized_json_is_skipped_with_warning(self):
        project_dir = make_project(
            self.temp_dir, files=[file_a_spec()]
        )
        with mock.patch.object(mixed_local_import, "MAX_LOCAL_JSON_BYTES", 10):
            result = build_local_graph(str(project_dir))

        # annotations.json 被跳过时该文件不产生任何节点，避免留下空文档节点；
        # annotations 不可用时不再读取 blocks.json，因此只有 1 条告警。
        self.assertEqual(result.nodes, [])
        self.assertEqual(result.edges, [])
        self.assertEqual(len(result.summary["warnings"]), 1)
        self.assertTrue(
            any("超过" in item for item in result.summary["warnings"])
        )

    def test_project_file_missing_is_not_found(self):
        project_dir = Path(self.temp_dir) / "not-a-project"
        project_dir.mkdir()
        with self.assertRaises(mixed_local_import.MixedLocalImportError) as ctx:
            build_local_graph(str(project_dir))
        self.assertEqual(ctx.exception.kind, "not_found")


# ============================================================
# POST /api/mixed/scan-local
# ============================================================

class ScanLocalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kb-local-scan-")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.client = TestClient(main_module.app)

    def _post(self, path):
        return self.client.post(
            "/api/mixed/scan-local", json={"path": path}
        )

    def test_scan_single_project(self):
        project_dir = make_rich_project(self.temp_dir)
        response = self._post(str(project_dir))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["path"], str(project_dir))
        self.assertEqual(data["base_dir"], self.temp_dir)
        self.assertEqual(len(data["projects"]), 1)
        project = data["projects"][0]
        self.assertEqual(project["dir"], str(project_dir))
        self.assertEqual(project["name"], "测试项目")
        self.assertEqual(project["labels"], ["材料", "设备"])
        self.assertEqual(project["relation_types"], ["ref"])
        self.assertEqual(project["file_count"], 2)
        self.assertEqual(project["file_names"], ["A标准.pdf", "B标准.pdf"])

    def test_scan_parent_directory_skips_dirs_without_project_json(self):
        projects_root = Path(self.temp_dir) / "projects"
        make_project(projects_root, "项目A", name="甲项目")
        (projects_root / "无项目目录").mkdir(parents=True)
        make_project(projects_root, "项目B", name="乙项目")
        (projects_root / "readme.txt").write_text("x", encoding="utf-8")

        response = self._post(str(projects_root))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["path"], str(projects_root))
        self.assertEqual(data["base_dir"], str(projects_root))
        self.assertEqual(
            [item["name"] for item in data["projects"]],
            ["乙项目", "甲项目"],
        )

    def test_scan_returns_400_for_relative_path(self):
        response = self._post("data/projects")
        self.assertEqual(response.status_code, 400)
        self.assertIn("绝对路径", response.json()["detail"])

    def test_scan_returns_404_for_missing_path(self):
        missing = str(Path(self.temp_dir) / "missing")
        response = self._post(missing)
        self.assertEqual(response.status_code, 404)
        self.assertIn("不存在", response.json()["detail"])

    def test_scan_returns_400_for_file_path(self):
        file_path = Path(self.temp_dir) / "a.txt"
        file_path.write_text("x", encoding="utf-8")
        response = self._post(str(file_path))
        self.assertEqual(response.status_code, 400)
        self.assertIn("不是文件夹", response.json()["detail"])

    def test_scan_returns_404_when_no_project_found(self):
        empty_root = Path(self.temp_dir) / "empty"
        (empty_root / "child").mkdir(parents=True)
        response = self._post(str(empty_root))
        self.assertEqual(response.status_code, 404)
        self.assertIn("没有找到混合标注项目", response.json()["detail"])


# ============================================================
# HTTP 测试基类：临时知识库项目目录
# ============================================================

class IsolatedProjectTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kb-local-import-")
        self.projects_dir = Path(self.temp_dir)
        self.index_file = self.projects_dir / "index.json"
        self.index_file.write_text("[]", encoding="utf-8")

        self.original_state = (
            main_module.PROJECTS_DIR,
            main_module.INDEX_FILE,
            main_module.graph_state,
            main_module._active_project_id,
        )
        main_module.PROJECTS_DIR = self.projects_dir
        main_module.INDEX_FILE = self.index_file
        main_module.graph_state = main_module.GraphState()
        main_module._active_project_id = None

        self.addCleanup(self._restore_globals)
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.client = TestClient(main_module.app)

    def _restore_globals(self):
        (
            main_module.PROJECTS_DIR,
            main_module.INDEX_FILE,
            main_module.graph_state,
            main_module._active_project_id,
        ) = self.original_state

    def seed_projects(self, names):
        projects = []
        for index, name in enumerate(names):
            projects.append({
                "id": "seed-%d" % index,
                "name": name,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            })
        self.index_file.write_text(
            json.dumps(projects, ensure_ascii=False), encoding="utf-8"
        )
        return projects

    def import_project(self, project_dir, project_name=None):
        payload = {"dir": str(project_dir)}
        if project_name is not None:
            payload["project_name"] = project_name
        return self.client.post("/api/mixed/import-local", json=payload)


# ============================================================
# POST /api/mixed/import-local
# ============================================================

class ImportLocalEndpointTests(IsolatedProjectTestCase):
    def test_import_creates_project_with_expected_graph(self):
        project_dir = make_rich_project(self.temp_dir)
        response = self.import_project(project_dir)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["project_name"], "测试项目")
        self.assertEqual(data["node_count"], 7)
        self.assertEqual(data["edge_count"], 6)
        self.assertEqual(data["summary"]["files"], 2)
        self.assertEqual(data["summary"]["file_names"], ["A标准.pdf", "B标准.pdf"])

        project_id = data["project_id"]
        self.assertTrue(
            (self.projects_dir / ("%s.json" % project_id)).exists()
        )

        index = json.loads(self.index_file.read_text(encoding="utf-8"))
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["id"], project_id)
        self.assertEqual(index[0]["name"], "测试项目")

        graph_response = self.client.get(
            "/api/graph", params={"project_id": project_id}
        )
        self.assertEqual(graph_response.status_code, 200)
        graph = graph_response.json()
        self.assertEqual(len(graph["nodes"]), 7)
        self.assertEqual(len(graph["edges"]), 6)
        self.assertEqual(graph["relation_weights"], {})
        self.assertEqual(graph["inference_rules"], [])
        self.assertEqual(graph["mutex_rules"], [])

        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(set(by_id), {
            "doc:f1",
            "fig:f1:tbl_0001",
            "ent:f1:1",
            "ent:f1:2",
            "doc:f2",
            "fig:f2:fig_0001",
            "ent:f2:1",
        })
        # 归属边全部是 kind=relation，不会注入 parent_id
        for node in graph["nodes"]:
            self.assertIsNone(node["parent_id"], node["id"])

        for node in graph["nodes"]:
            expected = (
                "labelfast:A标准.pdf"
                if node["id"].endswith(":f1") or ":f1:" in node["id"]
                else "labelfast:B标准.pdf"
            )
            self.assertEqual(node["origin"], expected, node["id"])

        coordinates = {(node["x"], node["y"]) for node in graph["nodes"]}
        self.assertEqual(len(coordinates), 7)

        edge_kinds = {edge["kind"] for edge in graph["edges"]}
        self.assertEqual(edge_kinds, {"relation"})
        relation_edges = [
            edge
            for edge in graph["edges"]
            if edge["relation"] == "ref"
        ]
        self.assertEqual(len(relation_edges), 1)
        self.assertEqual(relation_edges[0]["source"], "ent:f1:1")
        self.assertEqual(relation_edges[0]["target"], "ent:f1:2")

        ownership = [
            edge for edge in graph["edges"] if edge["relation"] == "属于"
        ]
        self.assertEqual(len(ownership), 5)
        for edge in ownership:
            self.assertTrue(edge["source"].startswith(("ent:", "fig:")))
            self.assertTrue(edge["target"].startswith("doc:"))
            self.assertEqual(edge["kind"], "relation")
            self.assertEqual(edge["weight"], 1.0)

    def test_import_without_blocks_keeps_flat_graph(self):
        project_dir = make_project(
            self.temp_dir, dir_name="仅B", name="仅B", files=[file_b_spec()]
        )
        response = self.import_project(project_dir)
        self.assertEqual(response.status_code, 200)

        graph = self.client.get(
            "/api/graph", params={"project_id": response.json()["project_id"]}
        ).json()
        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(set(by_id), {"doc:f2", "fig:f2:fig_0001", "ent:f2:1"})
        self.assertEqual(by_id["doc:f2"]["name"], "B标准")
        self.assertFalse(
            any(nid.startswith(("sec:", "par:")) for nid in by_id)
        )
        for edge in graph["edges"]:
            self.assertEqual(edge["relation"], "属于")

    def test_empty_project_returns_502_and_creates_no_project(self):
        project_dir = make_project(self.temp_dir, name="空项目")
        response = self.import_project(project_dir)

        self.assertEqual(response.status_code, 502)
        self.assertTrue(
            response.json()["detail"].startswith(
                "混合标注项目没有可导入的图谱数据"
            )
        )
        self.assertEqual(
            json.loads(self.index_file.read_text(encoding="utf-8")), []
        )
        self.assertEqual(
            sorted(path.name for path in self.projects_dir.glob("*.json")),
            ["index.json"],
        )

    def test_duplicate_name_gets_suffix_and_keeps_existing_project(self):
        seeded = self.seed_projects(["测试项目"])
        seed_file = self.projects_dir / ("%s.json" % seeded[0]["id"])
        seed_file.write_text('{"sentinel": true}', encoding="utf-8")

        project_dir = make_rich_project(self.temp_dir)
        response = self.import_project(project_dir)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["project_name"], "测试项目 (2)")
        self.assertNotEqual(data["project_id"], seeded[0]["id"])

        index = json.loads(self.index_file.read_text(encoding="utf-8"))
        self.assertEqual(len(index), 2)
        names = [item["name"] for item in index]
        self.assertIn("测试项目", names)
        self.assertIn("测试项目 (2)", names)
        self.assertEqual(
            seed_file.read_text(encoding="utf-8"), '{"sentinel": true}'
        )

    def test_project_name_override(self):
        project_dir = make_rich_project(self.temp_dir)
        response = self.import_project(project_dir, project_name="自定义名称")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project_name"], "自定义名称")

    def test_relative_path_returns_400(self):
        response = self.import_project("data/projects/测试项目")
        self.assertEqual(response.status_code, 400)
        self.assertIn("绝对路径", response.json()["detail"])
        self.assertEqual(
            json.loads(self.index_file.read_text(encoding="utf-8")), []
        )

    def test_missing_path_returns_404(self):
        missing = str(Path(self.temp_dir) / "missing")
        response = self.import_project(missing)
        self.assertEqual(response.status_code, 404)
        self.assertIn("不存在", response.json()["detail"])

    def test_directory_without_project_json_returns_404(self):
        not_project = Path(self.temp_dir) / "not-project"
        not_project.mkdir()
        response = self.import_project(not_project)
        self.assertEqual(response.status_code, 404)
        self.assertIn("缺少 project.json", response.json()["detail"])

    def test_graph_size_limit_returns_413_before_creating_project(self):
        project_dir = make_rich_project(self.temp_dir)
        with mock.patch.object(main_module, "MAX_IMPORT_NODES", 2):
            response = self.import_project(project_dir)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json()["detail"],
            "图谱规模超过上限（记录/节点/边）",
        )
        self.assertEqual(
            json.loads(self.index_file.read_text(encoding="utf-8")), []
        )

    def test_save_data_failure_returns_500_and_does_not_add_index(self):
        project_dir = make_rich_project(self.temp_dir)
        with mock.patch.object(
            main_module,
            "_write_project_data_strict",
            side_effect=OSError("disk full"),
        ):
            response = self.import_project(project_dir)

        self.assertEqual(response.status_code, 500)
        self.assertIn("保存项目数据失败", response.json()["detail"])
        self.assertEqual(
            json.loads(self.index_file.read_text(encoding="utf-8")), []
        )

    def test_save_index_failure_rolls_back_data_file(self):
        project_dir = make_rich_project(self.temp_dir)
        with mock.patch.object(
            main_module,
            "_save_project_index_strict",
            side_effect=OSError("read only"),
        ):
            response = self.import_project(project_dir)

        self.assertEqual(response.status_code, 500)
        self.assertIn("保存项目索引失败", response.json()["detail"])
        self.assertEqual(
            json.loads(self.index_file.read_text(encoding="utf-8")), []
        )
        self.assertEqual(
            sorted(path.name for path in self.projects_dir.glob("*.json")),
            ["index.json"],
        )

    def test_leader_view_source_distribution_includes_jsonl(self):
        project_dir = make_rich_project(self.temp_dir)
        response = self.import_project(project_dir)
        self.assertEqual(response.status_code, 200)
        project_id = response.json()["project_id"]

        with mock.patch.object(
            perspective_module, "PROJECTS_DIR", self.projects_dir
        ):
            leader = self.client.get(
                "/api/perspective/%s/leader" % project_id
            )

        self.assertEqual(leader.status_code, 200)
        distribution = leader.json()["summary"]["source_distribution"]
        self.assertGreaterEqual(distribution["jsonl"], 1)


# ============================================================
# perspective 来源映射
# ============================================================

class PerspectiveOriginTests(unittest.TestCase):
    def test_labelfast_maps_to_jsonl_and_keeps_file_name(self):
        self.assertEqual(
            _normalize_source_type("labelfast:标准.pdf"), "jsonl"
        )
        self.assertEqual(
            _parse_origin("labelfast:标准.pdf"), ("jsonl", "标准.pdf")
        )

    def test_existing_source_types_unchanged(self):
        self.assertEqual(_normalize_source_type("excel:表.xlsx"), "excel")
        self.assertEqual(_normalize_source_type("csv:表.csv"), "csv")
        self.assertEqual(_normalize_source_type("dameng"), "dameng")
        self.assertEqual(_normalize_source_type("manual"), "manual")


if __name__ == "__main__":
    unittest.main()
