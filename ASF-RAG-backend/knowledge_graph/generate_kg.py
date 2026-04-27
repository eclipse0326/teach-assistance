# generate_kg.py
import os
import requests
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel
import re
from langchain_community.document_loaders import PyPDFLoader
from docx import Document

router = APIRouter()

import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from models.model_config import get_model_config


# Constants
OLLAMA_API_URL = "http://localhost:11434/api/generate"
model_config = get_model_config()
OLLAMA_MODEL = model_config.kg_model
CHUNK_SIZE = 5000
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE_PATH = os.path.join(PROJECT_ROOT, "test")
DEFAULT_ONTOLOGY_PATH = os.path.join(PROJECT_ROOT, "knowledge_graph", "ontology_default.json")
KG_ONTOLOGY_ENFORCEMENT = os.getenv("KG_ONTOLOGY_ENFORCEMENT", "soft").strip().lower()
KG_FALLBACK_RELATION = os.getenv("KG_FALLBACK_RELATION", "Related_To").strip() or "Related_To"
KG_KEEP_ISOLATED_NODES = os.getenv("KG_KEEP_ISOLATED_NODES", "1") == "1"


class ProcessFileRequest(BaseModel):
    filename: str


class ProcessFilesResponse(BaseModel):
    message: str
    graph_data: dict


def normalize_label(value: Any) -> str:
    value = str(value or "").replace("\u3000", " ").strip()
    return re.sub(r"\s+", " ", value)


def canonical_node_id(label: str) -> str:
    normalized = normalize_label(label).lower()
    safe = re.sub(r"[^a-z0-9_]+", "_", normalized)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:80] if safe else ""


def load_json_file(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def normalize_ontology(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = raw if isinstance(raw, dict) else {}
    entity_types = [normalize_label(t) for t in (base.get("entity_types", []) or []) if normalize_label(t)]
    if not entity_types:
        entity_types = ["Data_Structure", "Algorithm", "Operation", "Complexity", "Concept", "Application", "Code_Snippet"]

    type_aliases: Dict[str, str] = {}
    for canonical, aliases in (base.get("entity_type_aliases", {}) or {}).items():
        canonical_norm = normalize_label(canonical)
        if not canonical_norm:
            continue
        type_aliases[canonical_norm.lower()] = canonical_norm
        for alias in aliases or []:
            alias_norm = normalize_label(alias)
            if alias_norm:
                type_aliases[alias_norm.lower()] = canonical_norm
    for et in entity_types:
        type_aliases[et.lower()] = et

    relations: Dict[str, Dict[str, Any]] = {}
    relation_aliases: Dict[str, str] = {}
    for rel, cfg in (base.get("relations", {}) or {}).items():
        rel_norm = normalize_label(rel)
        if not rel_norm:
            continue
        rel_cfg = cfg if isinstance(cfg, dict) else {}
        domain = [type_aliases.get(normalize_label(t).lower(), normalize_label(t)) for t in (rel_cfg.get("domain", []) or []) if normalize_label(t)]
        range_types = [type_aliases.get(normalize_label(t).lower(), normalize_label(t)) for t in (rel_cfg.get("range", []) or []) if normalize_label(t)]
        aliases = [normalize_label(a) for a in (rel_cfg.get("aliases", []) or []) if normalize_label(a)]
        relations[rel_norm] = {"domain": domain, "range": range_types, "aliases": aliases}
        relation_aliases[rel_norm.lower()] = rel_norm
        for alias in aliases:
            relation_aliases[alias.lower()] = rel_norm

    return {
        "name": normalize_label(base.get("name", "DataStructureOntology")) or "DataStructureOntology",
        "version": normalize_label(base.get("version", "1.0.0")) or "1.0.0",
        "entity_types": entity_types,
        "entity_type_aliases": type_aliases,
        "relations": relations,
        "relation_aliases": relation_aliases,
    }


def load_ontology_for_source(source_file_path: str) -> Dict[str, Any]:
    folder = os.path.dirname(source_file_path or "")
    candidates = []
    if folder:
        candidates.extend([
            os.path.join(folder, "ontology.json"),
            os.path.join(folder, "kg_ontology.json"),
        ])
        kb_meta = load_json_file(os.path.join(folder, "knowledge_data.json"))
        if kb_meta:
            ontology_file = normalize_label(kb_meta.get("ontology_file", ""))
            if ontology_file:
                candidates.append(
                    ontology_file if os.path.isabs(ontology_file) else os.path.join(folder, ontology_file)
                )
    candidates.append(DEFAULT_ONTOLOGY_PATH)
    for path in candidates:
        loaded = load_json_file(path)
        if loaded is not None:
            return normalize_ontology(loaded)
    return normalize_ontology({})


def canonical_entity_type(value: Any, ontology: Dict[str, Any]) -> str:
    normalized = normalize_label(value)
    if not normalized:
        return "Concept"
    aliases = ontology.get("entity_type_aliases", {}) or {}
    canonical = aliases.get(normalized.lower(), normalized)
    return canonical if canonical in set(ontology.get("entity_types", []) or []) else "Concept"


def canonical_relation(value: Any, ontology: Dict[str, Any]) -> str:
    normalized = normalize_label(value)
    if not normalized:
        return ""
    aliases = ontology.get("relation_aliases", {}) or {}
    return aliases.get(normalized.lower(), normalized)


def relation_is_valid(relation: str, source_type: str, target_type: str, ontology: Dict[str, Any]) -> bool:
    relations = ontology.get("relations", {}) or {}
    if not relations:
        return True
    cfg = relations.get(relation)
    if cfg is None:
        return False
    domain = set(cfg.get("domain", []) or [])
    range_types = set(cfg.get("range", []) or [])
    return (not domain or source_type in domain) and (not range_types or target_type in range_types)


# Split text into chunks
def split_text_into_chunks(text, chunk_size):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def get_graph_output_path(source_file_path: str) -> str:
    base_name = os.path.splitext(os.path.basename(source_file_path))[0]
    return os.path.join(os.path.dirname(source_file_path), f"{base_name}_graph.json")


def load_existing_graph_if_any(source_file_path: str) -> Optional[Dict[str, Any]]:
    graph_path = get_graph_output_path(source_file_path)
    if not os.path.exists(graph_path):
        return None
    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "nodes" in data and "edges" in data:
            return data
    except Exception as e:
        print(f"Existing graph file is unreadable, will regenerate: {graph_path}, error: {e}")
    return None


# Extract text from PDF
def extract_pdf_text(file_path):
    try:
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        text = "\n".join([doc.page_content for doc in documents])
        return text
    except Exception as e:
        print(f"Unable to extract PDF file {file_path}: {e}")
        return ""


# Extract text from DOC/DOCX
def extract_doc_text(file_path):
    try:
        doc = Document(file_path)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        print(f"Unable to extract DOC file {file_path}: {e}")
        return ""


# Extract text from text files
def extract_text_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Unable to read file {file_path}: {e}")
        return ""


# Extract text based on file type
def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_pdf_text(file_path)
    elif ext in [".doc", ".docx"]:
        return extract_doc_text(file_path)
    elif ext in [".txt", ".md"]:
        return extract_text_file(file_path)
    else:
        print(f"Unsupported file type: {ext}")
        return ""


# Extract graph data using Ollama API
def extract_graph_data(chunk: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
    allowed_types = "|".join(ontology.get("entity_types", []) or ["Concept"])
    relation_rules = []
    for rel_name, cfg in (ontology.get("relations", {}) or {}).items():
        domain = " | ".join(cfg.get("domain", []) or ["Any"])
        range_types = " | ".join(cfg.get("range", []) or ["Any"])
        relation_rules.append(f"- {rel_name}: domain=({domain}), range=({range_types})")
    relation_rules_text = "\n".join(relation_rules[:30]) if relation_rules else "- 无约束"

    prompt = f"""
你是一个知识图谱构建专家，请从以下文本中提取实体和关系，并以指定的JSON格式输出。

任务要求：
1. 提取文本中的实体作为节点，实体类型仅允许：{allowed_types}
2. 提取实体之间的关系作为边
3. 所有输出内容必须使用中文
4. 输出尽可能快速，详细和复杂，确保每个实体和关系都被正确识别
5. 要求关系之间互相联系，形成一个图
6. 优先使用如下本体关系并遵循其domain/range：
{relation_rules_text}

输出格式要求：
请严格按照以下JSON格式输出，包含"nodes"和"edges"两个字段：
- nodes: 包含对象的数组，每个对象有"id"（唯一标识符）、"label"（实体名称）和"type"（实体类型）
- edges: 包含对象的数组，每个对象有"source"（源节点id）、"target"（目标节点id）和"label"（关系描述）

示例输出格式：
{{
  "nodes": [{{"id": "entity1", "label": "实体1"}}, {{"id": "entity2", "label": "实体2"}}],
  "edges": [{{"source": "entity1", "target": "entity2", "label": "提及"}}]
}}

请处理以下文本：
{chunk}
"""
    data = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,  # Ensure full response is returned
    }
    try:
        response = requests.post(OLLAMA_API_URL, json=data, timeout=300)
        print(f"API request status code: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            generated_text = result.get("response", "")
            print(
                f"API response: {generated_text[:100]}..."
            )  # Print first 100 characters

            # Attempt to extract JSON from the response using regex
            json_pattern = r"(\{.*\})"
            match = re.search(json_pattern, generated_text, re.DOTALL)
            if match:
                json_str = match.group(1).strip()
                try:
                    parsed_json = json.loads(json_str)
                    if "nodes" in parsed_json and "edges" in parsed_json:
                        return parsed_json
                    else:
                        print(
                            "Warning: JSON does not contain 'nodes' and 'edges' keys."
                        )
                        return {"nodes": [], "edges": []}
                except json.JSONDecodeError:
                    print(f"Failed to parse extracted JSON: {json_str[:50]}...")
                    return {"nodes": [], "edges": []}
            else:
                print("No JSON object found in the response.")
                return {"nodes": [], "edges": []}
        else:
            print(f"API request failed, status code: {response.status_code}")
            return {"nodes": [], "edges": []}
    except Exception as e:
        print(f"API call error: {str(e)}")
        return {"nodes": [], "edges": []}


def merge_and_validate_graph(graph_data: Dict[str, Any], ontology: Dict[str, Any]) -> Dict[str, Any]:
    raw_nodes = graph_data.get("nodes", []) or []
    raw_edges = graph_data.get("edges", []) or []

    label_to_node: Dict[str, Dict[str, str]] = {}
    id_alias: Dict[str, str] = {}

    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        label = normalize_label(node.get("label", "") or node.get("id", ""))
        node_id = normalize_label(node.get("id", ""))
        node_type = canonical_entity_type(node.get("type", "Concept"), ontology)
        if not label:
            continue
        canonical_id = canonical_node_id(label)
        if not canonical_id:
            continue
        if label not in label_to_node:
            label_to_node[label] = {"id": canonical_id, "label": label, "type": node_type}
        if node_id:
            id_alias[node_id] = canonical_id
        id_alias[canonical_id] = canonical_id

    def resolve_node(value: Any) -> str:
        text = normalize_label(value)
        if not text:
            return ""
        if text in id_alias:
            return id_alias[text]
        if text in label_to_node:
            return label_to_node[text]["id"]
        generated = canonical_node_id(text)
        if not generated:
            return ""
        if text not in label_to_node:
            label_to_node[text] = {"id": generated, "label": text, "type": "Concept"}
        id_alias[generated] = generated
        return generated

    edges: List[Dict[str, Any]] = []
    edge_seen: Set[Tuple[str, str, str]] = set()
    node_by_id = {node["id"]: node for node in label_to_node.values()}
    generic_relations = {"提及", "相关", "有关", "关联", "联系"}

    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        relation_raw = normalize_label(edge.get("label", ""))
        relation = canonical_relation(relation_raw, ontology)
        source = resolve_node(edge.get("source", ""))
        target = resolve_node(edge.get("target", ""))
        if not source or not target or not relation or source == target:
            continue
        if relation in generic_relations:
            continue

        source_type = node_by_id.get(source, {}).get("type", "Concept")
        target_type = node_by_id.get(target, {}).get("type", "Concept")
        relation_valid = relation_is_valid(relation, source_type, target_type, ontology)
        if not relation_valid:
            if KG_ONTOLOGY_ENFORCEMENT == "strict":
                continue
            relation = canonical_relation(KG_FALLBACK_RELATION, ontology) or KG_FALLBACK_RELATION

        edge_key = (source, target, relation)
        if edge_key in edge_seen:
            continue
        edge_seen.add(edge_key)
        edges.append({
            "source": source,
            "target": target,
            "label": relation,
            "source_type": source_type,
            "target_type": target_type,
            "validated_by_ontology": relation_valid,
            "original_relation": relation_raw or relation
        })

    connected_ids: Set[str] = set()
    for edge in edges:
        connected_ids.add(edge["source"])
        connected_ids.add(edge["target"])

    nodes: List[Dict[str, Any]] = []
    for node in label_to_node.values():
        if KG_KEEP_ISOLATED_NODES or node["id"] in connected_ids:
            nodes.append(node)

    return {
        "nodes": nodes,
        "edges": edges,
        "ontology": {
            "name": ontology.get("name", "DataStructureOntology"),
            "version": ontology.get("version", "1.0.0"),
            "enforcement": KG_ONTOLOGY_ENFORCEMENT
        }
    }


def generate_graph_for_content(content: str, source_file_path: str) -> Dict[str, Any]:
    chunks = split_text_into_chunks(content, CHUNK_SIZE)
    ontology = load_ontology_for_source(source_file_path)
    graph_data = {"nodes": [], "edges": []}

    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i + 1}/{len(chunks)}")
        result = extract_graph_data(chunk, ontology)
        if result and "nodes" in result and "edges" in result:
            graph_data["nodes"].extend(result["nodes"])
            graph_data["edges"].extend(result["edges"])
        else:
            print(f"Failed to extract valid graph data for chunk {i + 1}")

    return merge_and_validate_graph(graph_data, ontology)


@router.post("/process-file", response_model=ProcessFilesResponse)
async def process_single_file(request: ProcessFileRequest):
    """
    处理单个文件并生成知识图谱数据
    """
    file_path = os.path.join(KNOWLEDGE_BASE_PATH, request.filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404, detail=f"File {request.filename} not found"
        )

    existing_graph = load_existing_graph_if_any(file_path)
    if existing_graph is not None:
        return ProcessFilesResponse(
            message=f"Skipped {request.filename}: existing graph found",
            graph_data=existing_graph,
        )

    # Extract text
    content = extract_text(file_path)
    if not content:
        raise HTTPException(
            status_code=400, detail=f"Unable to extract content from {request.filename}"
        )

    graph_data = generate_graph_for_content(content, file_path)

    return ProcessFilesResponse(
        message=f"Successfully processed {request.filename}", graph_data=graph_data
    )


@router.post("/process-all-files", response_model=List[ProcessFilesResponse])
async def process_all_files():
    """
    处理所有文件并生成知识图谱数据
    """
    if not os.path.exists(KNOWLEDGE_BASE_PATH):
        raise HTTPException(
            status_code=404, detail=f"Directory {KNOWLEDGE_BASE_PATH} does not exist"
        )

    files = [
        f
        for f in os.listdir(KNOWLEDGE_BASE_PATH)
        if os.path.isfile(os.path.join(KNOWLEDGE_BASE_PATH, f))
    ]

    results = []
    for file in files:
        try:
            file_path = os.path.join(KNOWLEDGE_BASE_PATH, file)
            if file.endswith("_graph.json"):
                continue
            print(f"Processing file: {file}")

            existing_graph = load_existing_graph_if_any(file_path)
            if existing_graph is not None:
                print(f"Skipping file {file}, existing graph found")
                results.append(
                    ProcessFilesResponse(
                        message=f"Skipped {file}: existing graph found", graph_data=existing_graph
                    )
                )
                continue

            # Extract text
            content = extract_text(file_path)
            if not content:
                print(f"Skipping file {file}, unable to extract content")
                continue

            graph_data = generate_graph_for_content(content, file_path)

            results.append(
                ProcessFilesResponse(
                    message=f"Successfully processed {file}", graph_data=graph_data
                )
            )

            # Save graph data
            output_file = get_graph_output_path(file_path)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(graph_data, f, indent=4, ensure_ascii=False)
            print(f"Graph data saved to {output_file}")

        except Exception as e:
            print(f"Error processing file {file}: {str(e)}")
            results.append(
                ProcessFilesResponse(
                    message=f"Error processing {file}: {str(e)}",
                    graph_data={"nodes": [], "edges": []},
                )
            )

    return results


@router.get("/get-graph-data/{filename}")
async def get_graph_data(filename: str):
    """
    获取特定文件的知识图谱数据
    """
    # Remove extension if present in filename
    name_without_ext = os.path.splitext(filename)[0]
    graph_filename = f"{name_without_ext}_graph.json"
    file_path = os.path.join(KNOWLEDGE_BASE_PATH, graph_filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404, detail=f"Graph data for {filename} not found"
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
        return graph_data
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error reading graph data: {str(e)}"
        )


######################################################################
# Generate graph


class ProcessFolderRequest(BaseModel):
    folder_path: str


@router.post("/process-knowledge-base", response_model=List[ProcessFilesResponse])
async def process_knowledge_base(request: ProcessFolderRequest):
    """
    处理指定知识库ID下的所有文档文件并生成知识图谱数据
    """
    kb_folder_path = os.path.join("local-KLB-files", request.folder_path)

    if not os.path.exists(kb_folder_path):
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge base directory {request.folder_path} does not exist",
        )

    if not os.path.isdir(kb_folder_path):
        raise HTTPException(
            status_code=400, detail=f"{kb_folder_path} is not a directory"
        )

    supported_extensions = [".pdf", ".doc", ".docx", ".txt", ".md"]
    files = [
        f
        for f in os.listdir(kb_folder_path)
        if os.path.isfile(os.path.join(kb_folder_path, f))
        and os.path.splitext(f)[1].lower() in supported_extensions
    ]

    if not files:
        return JSONResponse(
            content={
                "message": f"No supported files found in knowledge base {request.folder_path}"
            },
            status_code=200,
        )

    results = []
    for file in files:
        try:
            file_path = os.path.join(kb_folder_path, file)
            print(f"Processing file: {file}")

            existing_graph = load_existing_graph_if_any(file_path)
            if existing_graph is not None:
                print(f"Skipping file {file}, existing graph found")
                results.append(
                    ProcessFilesResponse(
                        message=f"Skipped {file}: existing graph found", graph_data=existing_graph
                    )
                )
                continue

            content = extract_text(file_path)
            if not content:
                print(f"Skipping file {file}, unable to extract content")
                continue

            graph_data = generate_graph_for_content(content, file_path)

            results.append(
                ProcessFilesResponse(
                    message=f"Successfully processed {file}", graph_data=graph_data
                )
            )

            # Knowledge graph
            output_file = get_graph_output_path(file_path)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(graph_data, f, indent=4, ensure_ascii=False)
            print(f"Graph data saved to {output_file}")

        except Exception as e:
            print(f"Error processing file {file}: {str(e)}")
            results.append(
                ProcessFilesResponse(
                    message=f"Error processing {file}: {str(e)}",
                    graph_data={"nodes": [], "edges": []},
                )
            )

    return results


@router.get("/get-kb-graph-data/{kb_id}/{filename}")
async def get_kb_graph_data(kb_id: str, filename: str):
    """
    获取特定知识库中特定文件的知识图谱数据
    """
    kb_folder_path = os.path.join("local-KLB-files", kb_id)

    if not os.path.exists(kb_folder_path):
        raise HTTPException(
            status_code=404, detail=f"Knowledge base directory {kb_id} not found"
        )

    name_without_ext = os.path.splitext(filename)[0]
    graph_filename = f"{name_without_ext}_graph.json"
    file_path = os.path.join(kb_folder_path, graph_filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Graph data for {filename} in knowledge base {kb_id} not found",
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
        return graph_data
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error reading graph data: {str(e)}"
        )


# ──────────────────────────────────────────────────────────
# Graph statistics
# ──────────────────────────────────────────────────────────


def _merge_graph_data(graph_list: List[dict]) -> dict:
    """
    合并多个图谱数据（去重节点 + 去重边）
    节点去重基于 id，边去重基于 (source, target, label) 三元组
    """
    merged_nodes: dict = {}  # id -> node
    merged_edges: dict = {}  # (source,target,label) -> edge

    for graph in graph_list:
        for node in graph.get("nodes", []):
            nid = node.get("id", "")
            if nid and nid not in merged_nodes:
                merged_nodes[nid] = node
        for edge in graph.get("edges", []):
            key = (
                edge.get("source", ""),
                edge.get("target", ""),
                edge.get("label", ""),
            )
            if key[0] and key[1] and key not in merged_edges:
                merged_edges[key] = edge

    return {
        "nodes": list(merged_nodes.values()),
        "edges": list(merged_edges.values()),
    }


@router.get("/get-kb-merged-graph/{kb_id}")
async def get_kb_merged_graph(kb_id: str):
    """
    获取指定知识库的**全合并图谱**
    将该知识库下所有 *_graph.json 合并为一个图，自动去重节点和边
    """
    kb_folder_path = os.path.join("local-KLB-files", kb_id)

    if not os.path.exists(kb_folder_path):
        raise HTTPException(status_code=404, detail=f"知识库目录 {kb_id} 不存在")

    graph_files = [
        f
        for f in os.listdir(kb_folder_path)
        if f.endswith("_graph.json") and os.path.isfile(os.path.join(kb_folder_path, f))
    ]

    if not graph_files:
        return {
            "nodes": [],
            "edges": [],
            "message": "该知识库暂无图谱数据，请先生成图谱",
        }

    graph_list = []
    for gf in graph_files:
        try:
            with open(os.path.join(kb_folder_path, gf), "r", encoding="utf-8") as f:
                graph_list.append(json.load(f))
        except Exception as e:
            print(f"[KG] 读取图谱文件 {gf} 失败: {e}")

    merged = _merge_graph_data(graph_list)
    merged["source_files"] = graph_files
    merged["node_count"] = len(merged["nodes"])
    merged["edge_count"] = len(merged["edges"])
    return merged


@router.get("/search-nodes/{kb_id}")
async def search_nodes(kb_id: str, keyword: str = ""):
    """
    在指定知识库的合并图谱中搜索节点（按 label 模糊匹配）
    返回匹配节点及其一跳邻居构成的子图
    """
    kb_folder_path = os.path.join("local-KLB-files", kb_id)

    if not os.path.exists(kb_folder_path):
        raise HTTPException(status_code=404, detail=f"知识库目录 {kb_id} 不存在")

    if not keyword.strip():
        raise HTTPException(status_code=400, detail="请提供搜索关键词")

    graph_files = [
        f
        for f in os.listdir(kb_folder_path)
        if f.endswith("_graph.json") and os.path.isfile(os.path.join(kb_folder_path, f))
    ]
    graph_list = []
    for gf in graph_files:
        try:
            with open(os.path.join(kb_folder_path, gf), "r", encoding="utf-8") as f:
                graph_list.append(json.load(f))
        except Exception:
            pass

    merged = _merge_graph_data(graph_list)
    kw_lower = keyword.lower()

    matched_ids = {
        n["id"]
        for n in merged["nodes"]
        if kw_lower in n.get("label", "").lower() or kw_lower in n.get("id", "").lower()
    }

    if not matched_ids:
        return {"nodes": [], "edges": [], "message": f"未找到包含 '{keyword}' 的节点"}

    neighbor_ids = set(matched_ids)
    subgraph_edges = []
    for edge in merged["edges"]:
        src, tgt = edge.get("source", ""), edge.get("target", "")
        if src in matched_ids or tgt in matched_ids:
            neighbor_ids.add(src)
            neighbor_ids.add(tgt)
            subgraph_edges.append(edge)

    subgraph_nodes = [n for n in merged["nodes"] if n["id"] in neighbor_ids]

    return {
        "nodes": subgraph_nodes,
        "edges": subgraph_edges,
        "matched_count": len(matched_ids),
        "keyword": keyword,
    }


@router.get("/graph-stats/{kb_id}")
async def get_graph_stats(kb_id: str):
    """
    获取知识库图谱统计信息：节点数、边数、节点类型分布、孤立节点数
    """
    kb_folder_path = os.path.join("local-KLB-files", kb_id)

    if not os.path.exists(kb_folder_path):
        raise HTTPException(status_code=404, detail=f"知识库目录 {kb_id} 不存在")

    graph_files = [
        f
        for f in os.listdir(kb_folder_path)
        if f.endswith("_graph.json") and os.path.isfile(os.path.join(kb_folder_path, f))
    ]

    graph_list = []
    for gf in graph_files:
        try:
            with open(os.path.join(kb_folder_path, gf), "r", encoding="utf-8") as f:
                graph_list.append(json.load(f))
        except Exception:
            pass

    merged = _merge_graph_data(graph_list)
    nodes = merged["nodes"]
    edges = merged["edges"]

    type_dist: dict = {}
    for n in nodes:
        t = n.get("type", "默认")
        type_dist[t] = type_dist.get(t, 0) + 1

    # 0
    connected_ids = set()
    for e in edges:
        connected_ids.add(e.get("source", ""))
        connected_ids.add(e.get("target", ""))
    isolated_count = sum(1 for n in nodes if n["id"] not in connected_ids)

    return {
        "kb_id": kb_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "type_distribution": type_dist,
        "isolated_node_count": isolated_count,
        "source_files": graph_files,
    }