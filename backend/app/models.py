"""共享数据模型 —— 新增数据源/视角模型"""

from __future__ import annotations

from typing import Dict, List

from enum import Enum
from pydantic import BaseModel, Field


# ============================================================
# 视角枚举
# ============================================================

class PerspectiveType(str, Enum):
    LEADER = "leader"
    ENGINEER = "engineer"
    PROCESS = "process"


# ============================================================
# 数据源连接器相关模型
# ============================================================

class TableInfo(BaseModel):
    """表/Sheet 元信息"""
    name: str
    table_schema: str = ""
    comment: str = ""
    row_count: int = 0


class ColumnInfo(BaseModel):
    """列/字段 元信息"""
    name: str
    data_type: str
    nullable: bool = True
    is_pk: bool = False
    comment: str = ""


class ImportSelection(BaseModel):
    """用户勾选的导入项"""
    source_id: str
    tables: List[str] = Field(default_factory=list)
    columns: Dict[str, List[str]] = Field(default_factory=dict)
    edited_names: Dict[str, str] = Field(default_factory=dict)


# ============================================================
# 多视角相关模型
# ============================================================

class DataSourceInfo(BaseModel):
    """数据源元信息（领导视角用）"""
    id: str
    name: str
    type: str
    conn_info: dict = Field(default_factory=dict)
    tables: List[str] = Field(default_factory=list)
    covered_nodes: int = 0
    covered_domains: List[str] = Field(default_factory=list)
    total_fields: int = 0
    covered_ontology_names: List[str] = Field(default_factory=list)


class BusinessDomain(BaseModel):
    """业务域（领导视角用）"""
    id: str
    name: str
    ontology_node_ids: List[str] = Field(default_factory=list)
    databases: List[str] = Field(default_factory=list)


class FieldMapping(BaseModel):
    """字段映射"""
    field_name: str
    attribute_key: str
    data_type: str


class DataMapping(BaseModel):
    """数据映射（工程师视角用）"""
    ontology_node_id: str
    source_type: str
    source_name: str
    table_name: str
    field_mappings: List[FieldMapping] = Field(default_factory=list)
    node_name: str = ""
    domain_id: str = ""


class LeaderViewData(BaseModel):
    """领导视角完整数据"""
    summary: dict = Field(default_factory=dict)
    data_sources: List[DataSourceInfo] = Field(default_factory=list)
    domains: List[BusinessDomain] = Field(default_factory=list)
    source_domain_map: dict = Field(default_factory=dict)


class EngineerViewData(BaseModel):
    """工程师视角完整数据"""
    project_name: str = ""
    nodes: list = Field(default_factory=list)
    mappings: List[DataMapping] = Field(default_factory=list)
    domains: List[BusinessDomain] = Field(default_factory=list)


# ============================================================
# JSONL 标注导入相关模型
# ============================================================

class JsonlImportSelection(BaseModel):
    """JSONL 导入请求"""
    source_id: str
