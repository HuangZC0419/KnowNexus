"""LabelFast graph.jsonl 导入解析测试。

覆盖：格式检测、节点 id 前缀、边 kind 映射、attributes 转换、
preserve_ids 汇总、坏行与空文件。测试使用临时 JSONL 文件。
"""

import json
import os
import tempfile
import unittest
import uuid

from app.services.jsonl_import import (
    GRAPH_FORMAT,
    is_graph_jsonl,
    parse_graph_jsonl,
)


def _dump(records):
    return "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in records
    )


SAMPLE_GRAPH = [
    {
        "record": "meta",
        "format": GRAPH_FORMAT,
        "file_name": "GBT 4423-2020.pdf",
        "exported_at": "2026-11-04T10:00:00",
    },
    {
        "record": "node",
        "id": "doc:f1",
        "kind": "document",
        "name": "GBT 4423-2020",
        "label": "文件",
        "attributes": {"standard": "GBT 4423-2020", "page": 1},
    },
    {
        "record": "node",
        "id": "sec:f1:s0005",
        "kind": "section",
        "name": "3.1 结构和尺寸",
        "label": "章节",
        "attributes": {"number": "3.1", "page": "3"},
    },
    {
        "record": "node",
        "id": "ent:f1:1",
        "kind": "entity",
        "name": "T2铜板",
        "label": "材料",
        "attributes": {"block_id": "b0009", "page": 4, "flag": True, "empty": None},
    },
    {
        "record": "edge",
        "id": "e:1",
        "source": "doc:f1",
        "target": "sec:f1:s0005",
        "relation": "包含",
        "kind": "hierarchy",
    },
    {
        "record": "edge",
        "id": "e:2",
        "source": "ent:f1:1",
        "target": "sec:f1:s0005",
        "relation": "出现在",
        "kind": "relation",
    },
]


class TempJsonlMixin:
    def write_temp(self, text, suffix=".jsonl", encoding="utf-8"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        with open(path, "w", encoding=encoding) as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path


class GraphDetectionTests(TempJsonlMixin, unittest.TestCase):
    def test_detects_graph_by_record_field(self):
        path = self.write_temp(_dump(SAMPLE_GRAPH))
        self.assertTrue(is_graph_jsonl(path))

    def test_detects_graph_by_format_only(self):
        path = self.write_temp(
            json.dumps({"format": GRAPH_FORMAT}, ensure_ascii=False) + "\n"
        )
        self.assertTrue(is_graph_jsonl(path))

    def test_ignores_legacy_annotation_jsonl(self):
        legacy = {
            "file_name": "a.pdf",
            "spans": [{"id": 1, "text": "甲", "label": "参数"}],
        }
        path = self.write_temp(_dump([legacy]))
        self.assertFalse(is_graph_jsonl(path))

    def test_empty_and_invalid_first_line_are_not_graph(self):
        self.assertFalse(is_graph_jsonl(self.write_temp("")))
        self.assertFalse(
            is_graph_jsonl(self.write_temp("not json\n" + _dump(SAMPLE_GRAPH)))
        )


class ParseGraphJsonlTests(TempJsonlMixin, unittest.TestCase):
    def parse_sample(self):
        return parse_graph_jsonl(self.write_temp(_dump(SAMPLE_GRAPH)))

    def test_node_ids_are_prefixed_and_fields_preserved(self):
        nodes, _, _ = self.parse_sample()
        self.assertEqual(
            [node["id"] for node in nodes],
            ["lf:doc:f1", "lf:sec:f1:s0005", "lf:ent:f1:1"],
        )
        document = nodes[0]
        self.assertEqual(document["name"], "GBT 4423-2020")
        self.assertEqual(document["label"], "文件")
        self.assertEqual(document["x"], 0)
        self.assertEqual(document["y"], 0)
        self.assertIsNone(document["parent_id"])
        self.assertEqual(document["origin"], "labelfast:GBT 4423-2020.pdf")

    def test_attributes_are_converted_to_key_value_strings(self):
        nodes, _, _ = self.parse_sample()
        self.assertEqual(
            nodes[2]["attributes"],
            [
                {"key": "block_id", "value": "b0009"},
                {"key": "page", "value": "4"},
                {"key": "flag", "value": "True"},
                {"key": "empty", "value": ""},
            ],
        )

    def test_edge_kind_and_weight_mapping(self):
        _, edges, _ = self.parse_sample()
        self.assertEqual(len(edges), 2)
        hierarchy, relation = edges
        self.assertEqual(hierarchy["kind"], "parent-child")
        self.assertIsNone(hierarchy["weight"])
        self.assertEqual(hierarchy["source"], "lf:doc:f1")
        self.assertEqual(hierarchy["target"], "lf:sec:f1:s0005")
        self.assertEqual(relation["kind"], "relation")
        self.assertEqual(relation["weight"], 1.0)
        for edge in edges:
            uuid.UUID(edge["id"])  # 必须是合法 uuid4 字符串
            self.assertEqual(edge["origin"], "labelfast:GBT 4423-2020.pdf")

    def test_summary_contains_preserve_ids_and_counts(self):
        _, _, summary = self.parse_sample()
        self.assertTrue(summary["preserve_ids"])
        self.assertEqual(summary["format"], GRAPH_FORMAT)
        self.assertEqual(summary["records"], 5)
        self.assertEqual(summary["node_count"], 3)
        self.assertEqual(summary["edge_count"], 2)
        self.assertEqual(summary["files"], 1)
        self.assertEqual(summary["entities"], 3)
        self.assertEqual(summary["relations"], 2)
        self.assertEqual(
            summary["labels"], {"文件": 1, "章节": 1, "材料": 1}
        )
        self.assertEqual(len(summary["sample_nodes"]), 3)
        self.assertEqual(len(summary["sample_edges"]), 2)
        self.assertEqual(summary["bad_lines"], 0)
        self.assertEqual(summary["total_lines"], 6)

    def test_existing_prefix_is_not_duplicated(self):
        path = self.write_temp(
            _dump(
                [
                    {
                        "record": "node",
                        "id": "lf:doc:f1",
                        "kind": "document",
                        "name": "a.pdf",
                        "label": "文件",
                        "attributes": {},
                    }
                ]
            )
        )
        nodes, _, _ = parse_graph_jsonl(path)
        self.assertEqual(nodes[0]["id"], "lf:doc:f1")

    def test_bad_line_is_counted_and_skipped(self):
        text = (
            json.dumps(
                {
                    "record": "node",
                    "id": "doc:1",
                    "name": "a.pdf",
                    "label": "文件",
                    "attributes": {},
                },
                ensure_ascii=False,
            )
            + "\nnot json\n"
            + json.dumps(
                {
                    "record": "edge",
                    "id": "e:1",
                    "source": "doc:1",
                    "target": "doc:1",
                    "relation": "包含",
                    "kind": "hierarchy",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        nodes, edges, summary = parse_graph_jsonl(self.write_temp(text))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(edges, [])  # 自环边被跳过
        self.assertEqual(summary["bad_lines"], 1)
        self.assertEqual(summary["total_lines"], 3)
        self.assertTrue(any("不是有效 JSON" in item for item in summary["warnings"]))

    def test_empty_file_returns_empty_graph_with_warning(self):
        nodes, edges, summary = parse_graph_jsonl(self.write_temp(""))
        self.assertEqual(nodes, [])
        self.assertEqual(edges, [])
        self.assertEqual(summary["records"], 0)
        self.assertEqual(summary["bad_lines"], 0)
        self.assertEqual(summary["total_lines"], 0)
        self.assertTrue(summary["preserve_ids"])
        self.assertEqual(summary["format"], GRAPH_FORMAT)
        self.assertTrue(any("文件为空" in item for item in summary["warnings"]))

    def test_all_bad_lines_reports_encoding_warning(self):
        nodes, edges, summary = parse_graph_jsonl(
            self.write_temp("坏行一\n坏行二\n")
        )
        self.assertEqual(nodes, [])
        self.assertEqual(edges, [])
        self.assertEqual(summary["bad_lines"], 2)
        self.assertEqual(summary["total_lines"], 2)
        self.assertIn("编码不匹配", summary["warnings"][0])

    def test_fallback_file_name_is_used_for_origin(self):
        path = self.write_temp(
            _dump(
                [
                    {
                        "record": "node",
                        "id": "doc:1",
                        "name": "a.pdf",
                        "label": "文件",
                        "attributes": {},
                    }
                ]
            )
        )
        nodes, _, _ = parse_graph_jsonl(path, "fallback.pdf")
        self.assertEqual(nodes[0]["origin"], "labelfast:fallback.pdf")


if __name__ == "__main__":
    unittest.main()
