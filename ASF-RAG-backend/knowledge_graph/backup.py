# generate_kg.py
import logging
import os
import requests
import json
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel
import re
from langchain_community.document_loaders import PyPDFLoader
from docx import Document

router = APIRouter()

# 修改导入语句，使用正确的绝对导入
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from models.model_config import get_model_config


# Constants
OLLAMA_API_URL = "http://localhost:11434/api/generate"
model_config = get_model_config()
OLLAMA_MODEL = model_config.kg_model
CHUNK_SIZE = 2800
CHUNK_OVERLAP = 400
KG_FAST_MODE = os.getenv("KG_FAST_MODE", "1") == "1"
KG_ENABLE_RULE_ENTITY_FALLBACK = os.getenv("KG_ENABLE_RULE_ENTITY_FALLBACK", "0") == "1"
MAX_RETRIES = 1 if KG_FAST_MODE else 3
REQUEST_TIMEOUT = 120 if KG_FAST_MODE else 300
MAX_CHUNK_WORKERS = 6 if KG_FAST_MODE else 4
MIN_NODE_FREQUENCY = 1
MIN_EDGE_FREQUENCY = 1
MIN_ENTITIES_PER_CHUNK = 6
KG_ONTOLOGY_ENFORCEMENT = os.getenv("KG_ONTOLOGY_ENFORCEMENT", "soft").strip().lower()
KG_KEEP_ISOLATED_NODES = os.getenv("KG_KEEP_ISOLATED_NODES", "1") == "1"
KG_FALLBACK_RELATION = os.getenv("KG_FALLBACK_RELATION", "Related_To").strip() or "Related_To"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE_PATH = os.path.join(PROJECT_ROOT, "test")
KG_CACHE_DIR = os.path.join(PROJECT_ROOT, "metadata", "kg_cache")
KG_CACHE_VERSION = "graphrag_v1"
DEFAULT_ONTOLOGY_PATH = os.path.join(PROJECT_ROOT, "knowledge_graph", "ontology_default.json")


class ProcessFileRequest(BaseModel):
    filename: str

class ProcessFilesResponse(BaseModel):
    message: str
    graph_data: dict


def load_json_file(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def normalize_ontology(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = raw if isinstance(raw, dict) else {}
    entity_types = [normalize_label(t) for t in (base.get("entity_types", []) or []) if normalize_label(t)]
    if not entity_types:
        entity_types = ["Data_Structure", "Algorithm", "Operation", "Complexity", "Concept", "Application", "Code_Snippet"]

    entity_type_aliases: Dict[str, str] = {}
    for canonical, aliases in (base.get("entity_type_aliases", {}) or {}).items():
        canonical_norm = normalize_label(canonical)
        if not canonical_norm:
            continue
        entity_type_aliases[canonical_norm.lower()] = canonical_norm
        for alias in aliases or []:
            alias_norm = normalize_label(alias)
            if alias_norm:
                entity_type_aliases[alias_norm.lower()] = canonical_norm
    for et in entity_types:
        entity_type_aliases[et.lower()] = et

    relations: Dict[str, Dict[str, Any]] = {}
    relation_aliases: Dict[str, str] = {}
    for relation, config in (base.get("relations", {}) or {}).items():
        rel_norm = normalize_label(relation)
        if not rel_norm:
            continue
        cfg = config if isinstance(config, dict) else {}
        domain = [entity_type_aliases.get(normalize_label(t).lower(), normalize_label(t)) for t in (cfg.get("domain", []) or []) if normalize_label(t)]
        range_types = [entity_type_aliases.get(normalize_label(t).lower(), normalize_label(t)) for t in (cfg.get("range", []) or []) if normalize_label(t)]
        aliases = [normalize_label(a) for a in (cfg.get("aliases", []) or []) if normalize_label(a)]
        relations[rel_norm] = {
            "domain": domain,
            "range": range_types,
            "aliases": aliases
        }
        relation_aliases[rel_norm.lower()] = rel_norm
        for alias in aliases:
            relation_aliases[alias.lower()] = rel_norm

    for relation, aliases in (base.get("relation_aliases", {}) or {}).items():
        rel_norm = normalize_label(relation)
        if not rel_norm:
            continue
        if rel_norm not in relations:
            relations[rel_norm] = {"domain": [], "range": [], "aliases": []}
        relation_aliases[rel_norm.lower()] = rel_norm
        for alias in aliases or []:
            alias_norm = normalize_label(alias)
            if alias_norm:
                relation_aliases[alias_norm.lower()] = rel_norm

    return {
        "name": normalize_label(base.get("name", "DataStructureOntology")) or "DataStructureOntology",
        "version": normalize_label(base.get("version", "1.0.0")) or "1.0.0",
        "entity_types": entity_types,
        "entity_type_aliases": entity_type_aliases,
        "relations": relations,
        "relation_aliases": relation_aliases,
    }


def load_ontology_for_source(source_file_path: str) -> Dict[str, Any]:
    kb_dir = os.path.dirname(source_file_path or "")
    candidates = []
    if kb_dir:
        candidates.extend([
            os.path.join(kb_dir, "ontology.json"),
            os.path.join(kb_dir, "kg_ontology.json"),
        ])
        kb_meta = load_json_file(os.path.join(kb_dir, "knowledge_data.json"))
        if kb_meta:
            ontology_path = normalize_label(str(kb_meta.get("ontology_file", "")))
            if ontology_path:
                if os.path.isabs(ontology_path):
                    candidates.append(ontology_path)
                else:
                    candidates.append(os.path.join(kb_dir, ontology_path))

    candidates.append(DEFAULT_ONTOLOGY_PATH)
    for path in candidates:
        loaded = load_json_file(path)
        if loaded is not None:
            return normalize_ontology(loaded)
    return normalize_ontology({})


def canonical_entity_type(value: str, ontology: Dict[str, Any]) -> str:
    normalized = normalize_label(value)
    if not normalized:
        return "Concept"
    aliases = ontology.get("entity_type_aliases", {}) or {}
    canonical = aliases.get(normalized.lower(), normalized)
    entity_types = set(ontology.get("entity_types", []) or [])
    if entity_types and canonical not in entity_types:
        return "Concept"
    return canonical


def canonical_relation(value: str, ontology: Dict[str, Any]) -> str:
    normalized = normalize_label(value)
    if not normalized:
        return ""
    aliases = ontology.get("relation_aliases", {}) or {}
    return aliases.get(normalized.lower(), normalized)


def relation_is_valid(
    relation: str,
    source_type: str,
    target_type: str,
    ontology: Dict[str, Any]
) -> bool:
    relations = ontology.get("relations", {}) or {}
    if not relations:
        return True
    relation_cfg = relations.get(relation)
    if relation_cfg is None:
        return False
    domain = set(relation_cfg.get("domain", []) or [])
    range_types = set(relation_cfg.get("range", []) or [])
    domain_ok = not domain or source_type in domain
    range_ok = not range_types or target_type in range_types
    return domain_ok and range_ok

# Split text into paragraph-aware chunks with overlap.
def split_text_into_chunks(text: str, chunk_size: int, overlap: int = CHUNK_OVERLAP) -> List[str]:
    if not text:
        return []

    cleaned_text = re.sub(r"\r\n?", "\n", text)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned_text) if p.strip()]
    if not paragraphs:
        paragraphs = [cleaned_text]

    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            # For an oversized paragraph, fallback to sentence-level split.
            sentences = re.split(r"(?<=[。！？；;.!?])", para)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(current) + len(sentence) + 1 <= chunk_size:
                    current = f"{current}\n{sentence}".strip()
                else:
                    if current:
                        chunks.append(current)
                    overlap_text = current[-overlap:] if current and overlap > 0 else ""
                    current = f"{overlap_text}\n{sentence}".strip() if overlap_text else sentence
            continue

        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            overlap_text = current[-overlap:] if current and overlap > 0 else ""
            current = f"{overlap_text}\n\n{para}".strip() if overlap_text else para

    if current:
        chunks.append(current)

    return chunks


def normalize_label(value: str) -> str:
    value = str(value or "").replace("\u3000", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def extract_candidate_keywords(text: str, top_k: int = 120) -> List[str]:
    if not text:
        return []

    normalized = normalize_label(text)
    # Common generic words that usually become low-value KG nodes.
    stopwords = {
        "我们", "你们", "它们", "这个", "那个", "其中", "以及", "或者", "如果", "因此", "所以",
        "可以", "需要", "通过", "对于", "进行", "实现", "方法", "过程", "步骤", "示例", "例子",
        "操作", "定义", "性质", "特点", "问题", "结果", "内容", "方式",
        "节点", "结点", "图中", "系统", "程序", "模块", "对象", "类型", "记录", "变量", "函数"
    }

    candidates = re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_\-]{2,}", normalized)
    freq: Dict[str, int] = {}
    for token in candidates:
        token = token.strip()
        if not token:
            continue
        if token.lower() in {"null", "none", "true", "false"}:
            continue
        if token in stopwords:
            continue
        if token.isdigit():
            continue
        freq[token] = freq.get(token, 0) + 1

    ranked = sorted(freq.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))
    # Keep tokens with more than one mention, fallback to top_k when sparse.
    filtered = [token for token, count in ranked if count >= 2][:top_k]
    if len(filtered) < min(20, top_k):
        filtered = [token for token, _ in ranked[:top_k]]
    return filtered


def extract_entities_by_rules(text: str, top_k: int = 120) -> List[str]:
    """
    Fast rule-based high-recall entity candidates (GraphRAG text-unit pass).
    """
    if not text:
        return []

    normalized = normalize_label(text)
    raw_terms = re.findall(
        r"[\u4e00-\u9fff]{2,16}|[A-Za-z][A-Za-z0-9_]{2,}|[A-Za-z]+算法|[A-Za-z]+Tree|[A-Za-z]+Node",
        normalized
    )

    # Keep this generic and lightweight: avoid domain-specific hint lists.
    stopwords = {
        "我们", "你们", "它们", "这个", "那个", "其中", "以及", "或者", "如果", "因此", "所以",
        "可以", "需要", "通过", "对于", "进行", "实现", "方法", "过程", "步骤", "示例", "例子",
        "章节", "内容", "说明",
        "typedef", "struct", "return", "const", "static", "public", "private", "protected",
        "int", "char", "float", "double", "void", "bool", "true", "false", "null", "none"
    }

    freq: Dict[str, int] = {}
    for term in raw_terms:
        term = normalize_label(term)
        if not term or term in stopwords or term.isdigit():
            continue
        if len(term) < 2:
            continue
        # Filter short code-like tokens that are usually noise.
        if re.fullmatch(r"[A-Za-z]{1,3}", term):
            continue
        freq[term] = freq.get(term, 0) + 1

    ranked = sorted(freq.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))
    # Keep frequent terms first to reduce random noise.
    filtered: List[str] = []
    for term, count in ranked:
        if count >= 2:
            filtered.append(term)
    return filtered[:top_k]


def build_global_entity_candidates(content: str) -> List[str]:
    """
    GraphRAG-style global entity pass: cheap recall before per-chunk relation extraction.
    """
    kw = extract_candidate_keywords(content, top_k=180)
    rule_entities = extract_entities_by_rules(content, top_k=180)
    merged = []
    seen = set()
    for item in kw + rule_entities:
        key = normalize_label(item).lower()
        if not key or key in seen:
            continue
        if is_noise_label(item):
            continue
        seen.add(key)
        merged.append(item)
    return merged[:220]


def select_keywords_for_chunk(chunk: str, keywords: List[str], max_keywords: int = 30) -> List[str]:
    if not chunk or not keywords:
        return []
    selected = [kw for kw in keywords if kw in chunk]
    return selected[:max_keywords]


def canonical_node_id(label: str) -> str:
    normalized = normalize_label(label).lower()
    safe = re.sub(r"[^a-z0-9_]+", "_", normalized)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe or len(safe) < 2:
        digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
        return f"n_{digest}"
    return safe[:80]


def extract_json_from_llm_output(text: str) -> Dict[str, Any]:
    if not text:
        return {"nodes": [], "edges": []}

    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(stripped):
        if ch != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[idx:])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    return {"nodes": [], "edges": []}


def is_noise_label(label: str) -> bool:
    if not label:
        return True
    if len(label) < 2:
        return True
    if len(label) > 32:
        return True
    if label.isdigit():
        return True

    generic_labels = {
        "提及", "相关", "有关", "关系", "内容", "对象", "类型",
        "定义", "方法", "过程", "步骤", "功能", "模块", "系统", "记录"
    }
    if label in generic_labels:
        return True

    low = label.lower()
    code_keywords = {
        "typedef", "struct", "return", "const", "static", "include", "define",
        "int", "char", "float", "double", "void", "bool", "true", "false", "null", "none"
    }
    if low in code_keywords:
        return True

    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,2}", label):
        return True
    # Too symbol-heavy fragments are not meaningful entities.
    if re.search(r"[{}[\]();=<>]", label):
        return True
    # Fragmented field-like names are often implementation details.
    if re.fullmatch(r"[a-z][a-z0-9_]{1,8}", label):
        return True
    return False


def optimize_graph_data(
    raw_graph_data: Dict[str, Any],
    preferred_keywords: Optional[set[str]] = None,
    keep_isolated_nodes: Optional[bool] = None
) -> Dict[str, List[Dict[str, str]]]:
    if keep_isolated_nodes is None:
        keep_isolated_nodes = KG_KEEP_ISOLATED_NODES
    raw_nodes = raw_graph_data.get("nodes", []) or []
    raw_edges = raw_graph_data.get("edges", []) or []

    label_to_node: Dict[str, Dict[str, str]] = {}
    id_alias: Dict[str, str] = {}

    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        label = normalize_label(node.get("label", ""))
        node_id = normalize_label(node.get("id", ""))
        node_type = normalize_label(node.get("type", "Concept")) or "Concept"
        if not label:
            continue

        canonical_id = canonical_node_id(label)
        if label not in label_to_node:
            label_to_node[label] = {"id": canonical_id, "label": label, "type": node_type}
        elif node_type and label_to_node[label].get("type", "Concept") == "Concept":
            label_to_node[label]["type"] = node_type

        if node_id:
            id_alias[node_id] = canonical_id

    def resolve_node(value: str) -> str:
        candidate = normalize_label(value)
        if not candidate:
            return ""
        if candidate in id_alias:
            return id_alias[candidate]
        # If the model returned label in source/target instead of id, normalize it as node.
        if candidate in label_to_node:
            return label_to_node[candidate]["id"]

        generated_id = canonical_node_id(candidate)
        if candidate not in label_to_node:
            label_to_node[candidate] = {"id": generated_id, "label": candidate}
        return generated_id

    generic_relations = {"提及", "相关", "有关", "关联", "联系"}
    dedup_edges: set[Tuple[str, str, str]] = set()
    final_edges: List[Dict[str, Any]] = []

    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        relation = normalize_label(edge.get("label", ""))
        source = resolve_node(edge.get("source", ""))
        target = resolve_node(edge.get("target", ""))
        source_type = normalize_label(edge.get("source_type", "")) or ""
        target_type = normalize_label(edge.get("target_type", "")) or ""
        validated_by_ontology = bool(edge.get("validated_by_ontology", False))

        if not source or not target or not relation:
            continue
        if relation in generic_relations:
            continue
        if source == target:
            continue

        edge_key = (source, target, relation)
        if edge_key in dedup_edges:
            continue
        dedup_edges.add(edge_key)
        final_edges.append({
            "source": source,
            "target": target,
            "label": relation,
            "source_type": source_type,
            "target_type": target_type,
            "validated_by_ontology": validated_by_ontology
        })

    preferred_keywords = preferred_keywords or set()
    node_degree: Dict[str, int] = {}
    for edge in final_edges:
        node_degree[edge["source"]] = node_degree.get(edge["source"], 0) + 1
        node_degree[edge["target"]] = node_degree.get(edge["target"], 0) + 1

    kept_ids: set[str] = set()
    for node in label_to_node.values():
        node_id = node["id"]
        node_label = node["label"]
        degree = node_degree.get(node_id, 0)
        keep_by_keyword = node_label in preferred_keywords
        if degree > 0 and not is_noise_label(node_label):
            kept_ids.add(node_id)
        elif keep_by_keyword and not is_noise_label(node_label):
            kept_ids.add(node_id)
        elif keep_isolated_nodes and not is_noise_label(node_label):
            kept_ids.add(node_id)

    filtered_edges = [
        edge for edge in final_edges
        if edge["source"] in kept_ids and edge["target"] in kept_ids
    ]
    final_nodes = [node for node in label_to_node.values() if node["id"] in kept_ids]
    return {"nodes": final_nodes, "edges": filtered_edges}


def get_document_topic_label(source_file_path: str) -> str:
    filename = os.path.basename(source_file_path)
    name_without_ext = os.path.splitext(filename)[0]
    # Remove timestamp/hash tails used in your current file naming style.
    topic = re.sub(r"-\d{8}_\d{6}_[0-9a-fA-F]{6,}$", "", name_without_ext)
    topic = normalize_label(topic)
    if not topic:
        topic = "文档知识主题"
    return topic


def make_graph_connected(graph_data: Dict[str, List[Dict[str, str]]], topic_label: str) -> Dict[str, List[Dict[str, str]]]:
    nodes = graph_data.get("nodes", []) or []
    edges = graph_data.get("edges", []) or []
    if not nodes:
        return {"nodes": [], "edges": []}

    node_ids = {str(node.get("id", "")).strip() for node in nodes if isinstance(node, dict)}
    node_ids = {n for n in node_ids if n}
    if not node_ids:
        return {"nodes": [], "edges": []}

    adjacency: Dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    degree: Dict[str, int] = {node_id: 0 for node_id in node_ids}

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target:
            continue
        if source not in adjacency or target not in adjacency:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1

    # Connected components on undirected projection.
    components: List[List[str]] = []
    visited: set[str] = set()
    for node_id in node_ids:
        if node_id in visited:
            continue
        stack = [node_id]
        comp: List[str] = []
        visited.add(node_id)
        while stack:
            current = stack.pop()
            comp.append(current)
            for nb in adjacency.get(current, set()):
                if nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        components.append(comp)

    if len(components) <= 1:
        return {"nodes": nodes, "edges": edges}

    topic_node_id = canonical_node_id(f"topic_{topic_label}")
    node_index = {str(node.get("id", "")).strip(): node for node in nodes if isinstance(node, dict)}
    if topic_node_id not in node_index:
        nodes.append({"id": topic_node_id, "label": topic_label})
        node_index[topic_node_id] = nodes[-1]

    edge_keys = {
        (
            str(edge.get("source", "")).strip(),
            str(edge.get("target", "")).strip(),
            normalize_label(edge.get("label", ""))
        )
        for edge in edges if isinstance(edge, dict)
    }

    # Link each disconnected component to the topic hub using its highest-degree node.
    for component in components:
        anchor = max(component, key=lambda node_id: degree.get(node_id, 0))
        bridge = (anchor, topic_node_id, "属于主题")
        if bridge not in edge_keys:
            edges.append({"source": anchor, "target": topic_node_id, "label": "属于主题"})
            edge_keys.add(bridge)

    return {"nodes": nodes, "edges": edges}


def build_community_reports(graph_data: Dict[str, Any], max_reports: int = 8) -> List[Dict[str, Any]]:
    """
    Build GraphRAG-like community reports from the graph structure.
    We treat non-bridge edges as local communities and generate deterministic summaries.
    """
    nodes = graph_data.get("nodes", []) or []
    edges = graph_data.get("edges", []) or []
    if not nodes or not edges:
        return []

    label_by_id: Dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "")).strip()
        label = normalize_label(node.get("label", ""))
        if node_id and label:
            label_by_id[node_id] = label

    node_ids = set(label_by_id.keys())
    adjacency: Dict[str, set[str]] = {nid: set() for nid in node_ids}
    usable_edges: List[Dict[str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        rel = normalize_label(edge.get("label", ""))
        if not source or not target or source not in node_ids or target not in node_ids:
            continue
        # Ignore synthetic bridge edges when building communities.
        if rel == "属于主题":
            continue
        usable_edges.append({"source": source, "target": target, "label": rel})
        adjacency[source].add(target)
        adjacency[target].add(source)

    visited: set[str] = set()
    communities: List[List[str]] = []
    for node_id in node_ids:
        if node_id in visited:
            continue
        stack = [node_id]
        comp: List[str] = []
        visited.add(node_id)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in adjacency.get(cur, set()):
                if nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        communities.append(comp)

    community_reports: List[Dict[str, Any]] = []
    for idx, comp in enumerate(communities, 1):
        comp_set = set(comp)
        comp_edges = [e for e in usable_edges if e["source"] in comp_set and e["target"] in comp_set]
        if not comp_edges:
            continue

        degree: Dict[str, int] = {nid: 0 for nid in comp}
        rel_counter: Dict[str, int] = {}
        for e in comp_edges:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
            degree[e["target"]] = degree.get(e["target"], 0) + 1
            rel = e["label"]
            rel_counter[rel] = rel_counter.get(rel, 0) + 1

        top_nodes = sorted(degree.items(), key=lambda x: x[1], reverse=True)[:6]
        top_entities = [label_by_id.get(nid, nid) for nid, _ in top_nodes]
        top_relations = [k for k, _ in sorted(rel_counter.items(), key=lambda x: x[1], reverse=True)[:5]]

        summary = (
            f"社区{idx}包含核心实体：{'、'.join(top_entities[:5])}；"
            f"主要关系类型：{'、'.join(top_relations[:4])}；"
            f"社区规模为{len(comp)}个实体、{len(comp_edges)}条关系。"
        )
        community_reports.append({
            "community_id": f"c{idx}",
            "node_ids": comp,
            "node_count": len(comp),
            "edge_count": len(comp_edges),
            "top_entities": top_entities,
            "top_relations": top_relations,
            "summary": summary
        })

    community_reports.sort(key=lambda x: (x["edge_count"], x["node_count"]), reverse=True)
    return community_reports[:max_reports]


def ensure_kg_cache_dir() -> None:
    os.makedirs(KG_CACHE_DIR, exist_ok=True)


def get_cache_file_path(source_file_path: str) -> str:
    file_token = hashlib.md5(source_file_path.encode("utf-8")).hexdigest()[:16]
    return os.path.join(KG_CACHE_DIR, f"{file_token}.json")


def load_kg_cache(source_file_path: str) -> Dict[str, Any]:
    ensure_kg_cache_dir()
    cache_path = get_cache_file_path(source_file_path)
    if not os.path.exists(cache_path):
        return {"chunks": {}}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("chunks"), dict):
            return data
    except Exception:
        pass
    return {"chunks": {}}


def save_kg_cache(source_file_path: str, cache: Dict[str, Any]) -> None:
    ensure_kg_cache_dir()
    cache_path = get_cache_file_path(source_file_path)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: failed to write KG cache {cache_path}: {e}")

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
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Unable to read file {file_path}: {e}")
        return ""

# Extract text based on file type
def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        return extract_pdf_text(file_path)
    elif ext in ['.doc', '.docx']:
        return extract_doc_text(file_path)
    elif ext in ['.txt', '.md']:
        return extract_text_file(file_path)
    else:
        print(f"Unsupported file type: {ext}")
        return ""

def build_graphrag_prompt(
    chunk: str,
    candidate_keywords: Optional[List[str]] = None,
    ontology: Optional[Dict[str, Any]] = None
) -> str:
    ontology = ontology or normalize_ontology({})
    keywords_hint = "、".join(candidate_keywords[:30]) if candidate_keywords else ""
    allowed_types = ontology.get("entity_types", []) or []
    relation_rules = []
    for rel_name, cfg in (ontology.get("relations", {}) or {}).items():
        domain = " | ".join(cfg.get("domain", []) or ["Any"])
        range_types = " | ".join(cfg.get("range", []) or ["Any"])
        relation_rules.append(f"- {rel_name}: domain=({domain}), range=({range_types})")
    relation_rules_text = "\n".join(relation_rules[:30]) if relation_rules else "- 无约束"

    if KG_FAST_MODE:
        return f"""
你是知识图谱抽取器。只输出JSON：
{{
  "entities":[{{"name":"","type":"{('|'.join(allowed_types) if allowed_types else 'Concept|Algorithm|Data_Structure|Operation|Complexity|Application|Code_Snippet')}","description":""}}],
  "relationships":[{{"source":"","target":"","relation":"","description":"","weight":0.0}}]
}}
要求：
1) 实体高召回：文本中出现的关键术语尽量保留；
2) 关系要具体，禁止“提及/相关/有关”；
3) source/target必须引用entities.name；
4) 若关系不确定，可少输出关系，但不要漏实体。
5) 关系尽量从本体关系中选择，关系约束如下：
{relation_rules_text}
候选关键词（优先覆盖）：{keywords_hint}
文本：{chunk}
"""
    return f"""
你是 GraphRAG 索引构建中的信息抽取器。任务是高召回、高准确地抽取“数据结构/算法”知识点实体与关系。

规则：
1) 只输出 JSON，不要输出任何解释、代码块或 Markdown。
2) 输出格式必须是：
{{
  "entities": [
    {{"name":"", "type":"{('|'.join(allowed_types) if allowed_types else 'Concept|Algorithm|Data_Structure|Operation|Complexity|Application|Code_Snippet')}", "description":""}}
  ],
  "relationships": [
    {{"source":"", "target":"", "relation":"", "description":"", "weight":0.0}}
  ]
}}
3) 实体 name 必须来自文本原文，优先提取：
   - 数据结构: 线性表/栈/队列/串/数组/树/图/哈希表/B树/AVL等
   - 算法: 排序/查找/图算法/动态规划等
   - 关键概念: 时间复杂度/空间复杂度/稳定性/有序性/邻接矩阵等
   - 操作与性质: 插入/删除/遍历/旋转/最短路径/最小生成树等
4) 关系必须具体语义，优先从以下集合中选：
   - 定义为, 包含, 属于, 实现方式, 前置条件, 后置条件, 时间复杂度, 空间复杂度, 用于, 等价于, 对比于, 依赖于, 优化于
   若不匹配再生成新关系，但禁止“提及/相关/有关”。
5) source/target 必须引用 entities 中 name，且禁止自环关系。
6) weight 范围为 0~1，表示关系置信度。
7) 如果给出“候选关键词”，优先覆盖这些词（前提是文本中确实出现且语义成立）。
8) 如果文本中出现术语但缺少明确关系，仍应保留实体；仅在关系确凿时输出 relationships。
9) 不要把纯语法词、代词、章节编号当成实体。
10) 优先使用本体关系并遵循domain/range约束：
{relation_rules_text}

抽取流程（按此顺序执行）：
A. 先扫描文本列出所有候选术语实体；
B. 再删除明显噪声词；
C. 再建立实体间关系；
D. 最后检查 source/target 是否都存在于 entities.name。

候选关键词（可为空）：
{keywords_hint}

文本：
{chunk}
"""


def extract_graph_data_map(
    chunk: str,
    candidate_keywords: Optional[List[str]] = None,
    ontology: Optional[Dict[str, Any]] = None
):
    prompt = build_graphrag_prompt(chunk, candidate_keywords, ontology=ontology)
    data = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False  # Ensure full response is returned
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(OLLAMA_API_URL, json=data, timeout=REQUEST_TIMEOUT)
            print(f"API request status code: {response.status_code}")
            if response.status_code != 200:
                print(f"API request failed, status code: {response.status_code}")
                continue

            result = response.json()
            generated_text = result.get("response", "")
            print(f"API response: {generated_text[:120]}...")

            parsed_json = extract_json_from_llm_output(generated_text)
            if "entities" in parsed_json and "relationships" in parsed_json:
                entities = parsed_json.get("entities", []) or []
                relationships = parsed_json.get("relationships", []) or []

                # Sparse fallback: for long chunks, one extra targeted pass to recover missed entities.
                if not KG_FAST_MODE and len(chunk) > 900 and len(entities) < MIN_ENTITIES_PER_CHUNK:
                    keywords_hint = "、".join((candidate_keywords or [])[:40])
                    repair_prompt = f"""
你上一次抽取遗漏较多。请重新抽取并提高召回率，仍只输出 JSON。
要求：
1) 保留原格式: {{"entities":[...], "relationships":[...]}}
2) 优先覆盖这些术语（若文本中出现）: {keywords_hint}
3) 对于术语之间关系不明确时，可先输出实体，关系可少量但需准确。

文本：
{chunk}
"""
                    repair_payload = {"model": OLLAMA_MODEL, "prompt": repair_prompt, "stream": False}
                    repair_resp = requests.post(OLLAMA_API_URL, json=repair_payload, timeout=REQUEST_TIMEOUT)
                    if repair_resp.status_code == 200:
                        repair_json = extract_json_from_llm_output(repair_resp.json().get("response", ""))
                        if "entities" in repair_json and "relationships" in repair_json:
                            if len(repair_json.get("entities", []) or []) >= len(entities):
                                parsed_json = repair_json
                                entities = parsed_json.get("entities", []) or []
                                relationships = parsed_json.get("relationships", []) or []

                # Optional rule fallback (disabled by default for GraphRAG-style behavior).
                if KG_ENABLE_RULE_ENTITY_FALLBACK:
                    fallback_entities = extract_entities_by_rules(chunk, top_k=40)
                    existing = {normalize_label(e.get("name", "")).lower() for e in entities if isinstance(e, dict)}
                    for term in fallback_entities:
                        key = normalize_label(term).lower()
                        if not key or key in existing:
                            continue
                        if is_noise_label(term):
                            continue
                        entities.append({"name": term, "type": "Concept", "description": "规则补充实体"})
                        existing.add(key)

                parsed_json["entities"] = entities
                parsed_json["relationships"] = relationships
                return parsed_json

            print("Warning: JSON does not contain expected map keys.")
        except Exception as e:
            print(f"API call error on attempt {attempt}: {str(e)}")

        if attempt < MAX_RETRIES:
            time.sleep(1.5 * attempt)

    return {"entities": [], "relationships": []}


def merge_graphrag_map_results(
    map_results: List[Dict[str, Any]],
    preferred_keywords: Optional[set[str]] = None,
    ontology: Optional[Dict[str, Any]] = None
) -> Dict[str, List[Dict[str, str]]]:
    ontology = ontology or normalize_ontology({})
    preferred_keywords = preferred_keywords or set()
    entity_stats: Dict[str, Dict[str, Any]] = {}
    relation_stats: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    def entity_key(name: str) -> str:
        return normalize_label(name).lower()

    for result in map_results:
        entities = result.get("entities", []) or []
        relationships = result.get("relationships", []) or []

        current_entities: Dict[str, str] = {}
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = normalize_label(entity.get("name", ""))
            e_type = canonical_entity_type(entity.get("type", "Concept"), ontology)
            desc = normalize_label(entity.get("description", ""))
            if not name or is_noise_label(name):
                continue
            key = entity_key(name)
            current_entities[key] = name
            if key not in entity_stats:
                entity_stats[key] = {
                    "label": name,
                    "types": {e_type: 1},
                    "description": desc,
                    "freq": 1,
                }
            else:
                entity_stats[key]["freq"] += 1
                entity_stats[key]["types"][e_type] = entity_stats[key]["types"].get(e_type, 0) + 1
                if not entity_stats[key]["description"] and desc:
                    entity_stats[key]["description"] = desc

        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            src_raw = normalize_label(rel.get("source", ""))
            tgt_raw = normalize_label(rel.get("target", ""))
            original_relation = normalize_label(rel.get("relation", ""))
            relation = canonical_relation(original_relation, ontology)
            rel_desc = normalize_label(rel.get("description", ""))
            weight_raw = rel.get("weight", 0.5)
            try:
                weight = float(weight_raw)
            except Exception:
                weight = 0.5
            weight = min(1.0, max(0.0, weight))

            if not src_raw or not tgt_raw or not relation:
                continue
            src_key = entity_key(src_raw)
            tgt_key = entity_key(tgt_raw)
            if src_key == tgt_key:
                continue
            if relation in {"提及", "相关", "有关", "关联", "联系"}:
                continue
            if src_key not in current_entities or tgt_key not in current_entities:
                continue
            source_type = max(entity_stats.get(src_key, {}).get("types", {"Concept": 1}).items(), key=lambda x: x[1])[0]
            target_type = max(entity_stats.get(tgt_key, {}).get("types", {"Concept": 1}).items(), key=lambda x: x[1])[0]
            relation_valid = relation_is_valid(relation, source_type, target_type, ontology)
            if not relation_valid:
                if KG_ONTOLOGY_ENFORCEMENT == "strict":
                    continue
                relation = canonical_relation(KG_FALLBACK_RELATION, ontology)
                if not relation:
                    relation = KG_FALLBACK_RELATION

            rel_key = (src_key, tgt_key, relation)
            if rel_key not in relation_stats:
                relation_stats[rel_key] = {
                    "freq": 1,
                    "weight_sum": weight,
                    "description": rel_desc,
                    "source_type": source_type,
                    "target_type": target_type,
                    "validated_by_ontology": relation_valid,
                    "original_relation": original_relation
                }
            else:
                relation_stats[rel_key]["freq"] += 1
                relation_stats[rel_key]["weight_sum"] += weight
                if not relation_stats[rel_key]["description"] and rel_desc:
                    relation_stats[rel_key]["description"] = rel_desc
                relation_stats[rel_key]["validated_by_ontology"] = (
                    relation_stats[rel_key].get("validated_by_ontology", True) and relation_valid
                )
                if not relation_stats[rel_key].get("original_relation") and original_relation:
                    relation_stats[rel_key]["original_relation"] = original_relation

    raw_graph_data = {"nodes": [], "edges": []}
    label_by_key: Dict[str, str] = {}
    keep_keys: set[str] = set()

    for key, stats in entity_stats.items():
        label = stats["label"]
        freq = stats["freq"]
        if freq >= MIN_NODE_FREQUENCY or label in preferred_keywords:
            keep_keys.add(key)
            label_by_key[key] = label
            major_type = max(stats["types"].items(), key=lambda x: x[1])[0] if stats.get("types") else "Concept"
            raw_graph_data["nodes"].append({
                "id": canonical_node_id(label),
                "label": label,
                "type": major_type
            })

    for (src_key, tgt_key, relation), stats in relation_stats.items():
        if src_key not in keep_keys or tgt_key not in keep_keys:
            continue
        if stats["freq"] < MIN_EDGE_FREQUENCY:
            continue
        source_label = label_by_key[src_key]
        target_label = label_by_key[tgt_key]
        raw_graph_data["edges"].append({
            "source": canonical_node_id(source_label),
            "target": canonical_node_id(target_label),
            "label": relation,
            "source_type": stats.get("source_type", "Concept"),
            "target_type": stats.get("target_type", "Concept"),
            "validated_by_ontology": bool(stats.get("validated_by_ontology", False)),
            "original_relation": stats.get("original_relation", relation)
        })

    return optimize_graph_data(
        raw_graph_data,
        preferred_keywords,
        keep_isolated_nodes=KG_KEEP_ISOLATED_NODES
    )


def extract_map_results_parallel(
    chunks: List[str],
    candidate_keywords: List[str],
    source_file_path: str,
    ontology: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    if not chunks:
        return []

    ontology = ontology or normalize_ontology({})
    ontology_token = hashlib.md5(
        json.dumps(
            {
                "name": ontology.get("name", ""),
                "version": ontology.get("version", ""),
                "entity_types": ontology.get("entity_types", []),
                "relations": ontology.get("relations", {}),
            },
            ensure_ascii=False,
            sort_keys=True
        ).encode("utf-8")
    ).hexdigest()[:12]

    cache = load_kg_cache(source_file_path)
    chunk_cache = cache.get("chunks", {})
    results: List[Dict[str, Any]] = [{"entities": [], "relationships": []} for _ in chunks]

    futures = {}
    workers = min(MAX_CHUNK_WORKERS, max(1, len(chunks)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for i, chunk in enumerate(chunks):
            chunk_hash = hashlib.md5(
                f"{KG_CACHE_VERSION}|{OLLAMA_MODEL}|{ontology_token}|{chunk}".encode("utf-8")
            ).hexdigest()
            if chunk_hash in chunk_cache:
                results[i] = chunk_cache[chunk_hash]
                continue

            chunk_keywords = select_keywords_for_chunk(chunk, candidate_keywords)
            future = executor.submit(extract_graph_data_map, chunk, chunk_keywords, ontology)
            futures[future] = (i, chunk_hash)

        for future in as_completed(futures):
            i, chunk_hash = futures[future]
            try:
                res = future.result()
                if not isinstance(res, dict):
                    res = {"entities": [], "relationships": []}
            except Exception as e:
                print(f"Chunk extraction failed ({i}): {e}")
                res = {"entities": [], "relationships": []}
            results[i] = res
            chunk_cache[chunk_hash] = res

    cache["chunks"] = chunk_cache
    save_kg_cache(source_file_path, cache)
    return results


def generate_graph_for_content(content: str, source_file_path: str) -> Dict[str, Any]:
    ontology = load_ontology_for_source(source_file_path)
    chunks = split_text_into_chunks(content, CHUNK_SIZE)
    candidate_keywords = build_global_entity_candidates(content)
    map_results = extract_map_results_parallel(chunks, candidate_keywords, source_file_path, ontology=ontology)
    graph_data = merge_graphrag_map_results(map_results, set(candidate_keywords), ontology=ontology)
    topic_label = get_document_topic_label(source_file_path)
    connected_graph = make_graph_connected(graph_data, topic_label)
    community_reports = build_community_reports(connected_graph)
    connected_graph["community_reports"] = community_reports
    connected_graph["ontology"] = {
        "name": ontology.get("name", "DataStructureOntology"),
        "version": ontology.get("version", "1.0.0")
    }
    return connected_graph

@router.post("/process-file", response_model=ProcessFilesResponse)
async def process_single_file(request: ProcessFileRequest):
    """
    处理单个文件并生成知识图谱数据
    """
    file_path = os.path.join(KNOWLEDGE_BASE_PATH, request.filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File {request.filename} not found")

    # Extract text
    content = extract_text(file_path)
    if not content:
        raise HTTPException(status_code=400, detail=f"Unable to extract content from {request.filename}")

    graph_data = generate_graph_for_content(content, file_path)

    return ProcessFilesResponse(
        message=f"Successfully processed {request.filename}",
        graph_data=graph_data
    )


@router.post("/process-all-files", response_model=List[ProcessFilesResponse])
async def process_all_files():
    """
    处理所有文件并生成知识图谱数据
    """
    if not os.path.exists(KNOWLEDGE_BASE_PATH):
        raise HTTPException(status_code=404, detail=f"Directory {KNOWLEDGE_BASE_PATH} does not exist")

    files = [f for f in os.listdir(KNOWLEDGE_BASE_PATH) if os.path.isfile(os.path.join(KNOWLEDGE_BASE_PATH, f))]

    results = []
    for file in files:
        try:
            file_path = os.path.join(KNOWLEDGE_BASE_PATH, file)
            print(f"Processing file: {file}")

            # Extract text
            content = extract_text(file_path)
            if not content:
                print(f"Skipping file {file}, unable to extract content")
                continue

            graph_data = generate_graph_for_content(content, file_path)

            results.append(ProcessFilesResponse(
                message=f"Successfully processed {file}",
                graph_data=graph_data
            ))

            # Save cumulative graph data
            output_file = os.path.join(KNOWLEDGE_BASE_PATH, f"{os.path.splitext(file)[0]}_graph.json")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(graph_data, f, indent=4, ensure_ascii=False)
            print(f"Graph data saved to {output_file}")

        except Exception as e:
            print(f"Error processing file {file}: {str(e)}")
            results.append(ProcessFilesResponse(
                message=f"Error processing {file}: {str(e)}",
                graph_data={"nodes": [], "edges": []}
            ))

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
        raise HTTPException(status_code=404, detail=f"Graph data for {filename} not found")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            graph_data = json.load(f)
        return graph_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading graph data: {str(e)}")




######################################################################
#新增，处理知识库文件夹生成图谱


class ProcessFolderRequest(BaseModel):
    folder_path: str


@router.post("/process-knowledge-base", response_model=List[ProcessFilesResponse])
async def process_knowledge_base(request: ProcessFolderRequest):
    """
    处理指定知识库ID下的所有文档文件并生成知识图谱数据
    """
    # 构建知识库文件夹路径 - 使用与系统其他部分一致的路径
    kb_folder_path = os.path.join("local-KLB-files", request.folder_path)

    if not os.path.exists(kb_folder_path):
        raise HTTPException(status_code=404, detail=f"Knowledge base directory {request.folder_path} does not exist")

    if not os.path.isdir(kb_folder_path):
        raise HTTPException(status_code=400, detail=f"{kb_folder_path} is not a directory")

    # 获取文件夹中所有支持的文件类型
    supported_extensions = ['.pdf', '.doc', '.docx', '.txt', '.md']
    files = [f for f in os.listdir(kb_folder_path)
             if os.path.isfile(os.path.join(kb_folder_path, f))
             and os.path.splitext(f)[1].lower() in supported_extensions]

    if not files:
        return JSONResponse(
            content={"message": f"No supported files found in knowledge base {request.folder_path}"},
            status_code=200
        )

    results = []
    for file in files:
        try:
            file_path = os.path.join(kb_folder_path, file)
            print(f"Processing file: {file}")

            # 提取文本
            content = extract_text(file_path)
            if not content:
                print(f"Skipping file {file}, unable to extract content")
                continue

            graph_data = generate_graph_for_content(content, file_path)


            # 添加到结果列表
            results.append(ProcessFilesResponse(
                message=f"Successfully processed {file}",
                graph_data=graph_data
            ))

            # 保存生成的知识图谱数据
            output_file = os.path.join(kb_folder_path, f"{os.path.splitext(file)[0]}_graph.json")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(graph_data, f, indent=4, ensure_ascii=False)
            print(f"Graph data saved to {output_file}")

        except Exception as e:
            print(f"Error processing file {file}: {str(e)}")
            results.append(ProcessFilesResponse(
                message=f"Error processing {file}: {str(e)}",
                graph_data={"nodes": [], "edges": []}
            ))

    return results





@router.get("/get-kb-graph-data/{kb_id}/{filename}")
async def get_kb_graph_data(kb_id: str, filename: str):
    """
    获取特定知识库中特定文件的知识图谱数据
    """
    # 构建知识库文件夹路径
    kb_folder_path = os.path.join("local-KLB-files", kb_id)

    if not os.path.exists(kb_folder_path):
        raise HTTPException(status_code=404, detail=f"Knowledge base directory {kb_id} not found")

    # 移除文件名中的扩展名（如果存在）
    name_without_ext = os.path.splitext(filename)[0]
    graph_filename = f"{name_without_ext}_graph.json"
    file_path = os.path.join(kb_folder_path, graph_filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Graph data for {filename} in knowledge base {kb_id} not found")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            graph_data = json.load(f)
        return graph_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading graph data: {str(e)}")
