import json
import os
import re
from typing import Dict, List, Tuple, Any


class LocalGraphRAGRetriever:
    """Lightweight graph retriever over local *_graph.json files."""

    def __init__(self, docs_dir: str):
        self.docs_dir = docs_dir

    def _iter_graph_files(self) -> List[str]:
        if not self.docs_dir or not os.path.isdir(self.docs_dir):
            return []

        graph_files: List[str] = []
        ignored_dirs = {"vectorstore", "__pycache__", ".git", ".cursor"}
        for root, dirs, files in os.walk(self.docs_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for filename in files:
                if filename.endswith("_graph.json"):
                    graph_files.append(os.path.join(root, filename))
        return graph_files

    def _load_graph_data(self) -> Tuple[Dict[str, str], List[Dict[str, str]], List[Dict[str, Any]], List[str]]:
        nodes_by_id: Dict[str, str] = {}
        edges: List[Dict[str, str]] = []
        community_reports: List[Dict[str, Any]] = []
        sources: List[str] = []

        for graph_file in self._iter_graph_files():
            try:
                with open(graph_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sources.append(graph_file)
            except Exception:
                continue

            for node in data.get("nodes", []) or []:
                if not isinstance(node, dict):
                    continue
                node_id = str(node.get("id", "")).strip()
                label = str(node.get("label", "")).strip()
                if not node_id or not label:
                    continue
                nodes_by_id[node_id] = label

            for edge in data.get("edges", []) or []:
                if not isinstance(edge, dict):
                    continue
                source = str(edge.get("source", "")).strip()
                target = str(edge.get("target", "")).strip()
                label = str(edge.get("label", "")).strip()
                if not source or not target or not label:
                    continue
                if source == target:
                    continue
                edges.append({"source": source, "target": target, "label": label})

            for report in data.get("community_reports", []) or []:
                if not isinstance(report, dict):
                    continue
                summary = str(report.get("summary", "")).strip()
                if not summary:
                    continue
                community_reports.append(report)

        return nodes_by_id, edges, community_reports, sources

    def _tokenize_query(self, query: str) -> List[str]:
        if not query:
            return []
        lowered = query.lower()
        tokens = re.findall(r"[\u4e00-\u9fff]{2,12}|[a-z0-9_]{2,}", lowered)
        # Preserve order while deduping.
        return list(dict.fromkeys(tokens))

    def retrieve(self, query: str, top_nodes: int = 12, top_edges: int = 3) -> Dict[str, Any]:
        nodes_by_id, edges, community_reports, graph_sources = self._load_graph_data()
        if not nodes_by_id or not edges:
            return {
                "context": "",
                "matched_nodes": [],
                "matched_edges": [],
                "matched_communities": [],
                "best_edge_score": 0.0,
                "best_edge_overlap": 0,
                "graph_sources": graph_sources
            }

        tokens = self._tokenize_query(query)
        if not tokens:
            return {
                "context": "",
                "matched_nodes": [],
                "matched_edges": [],
                "matched_communities": [],
                "best_edge_score": 0.0,
                "best_edge_overlap": 0,
                "graph_sources": graph_sources
            }

        degree: Dict[str, int] = {}
        for edge in edges:
            degree[edge["source"]] = degree.get(edge["source"], 0) + 1
            degree[edge["target"]] = degree.get(edge["target"], 0) + 1

        node_scores: Dict[str, float] = {}
        for node_id, label in nodes_by_id.items():
            label_lower = label.lower()
            hits = [t for t in tokens if t in label_lower]
            if not hits:
                continue
            score = sum(len(t) for t in hits) + degree.get(node_id, 0) * 0.25
            node_scores[node_id] = score

        if not node_scores:
            return {
                "context": "",
                "matched_nodes": [],
                "matched_edges": [],
                "matched_communities": [],
                "best_edge_score": 0.0,
                "best_edge_overlap": 0,
                "graph_sources": graph_sources
            }

        ranked_nodes = sorted(node_scores.items(), key=lambda x: x[1], reverse=True)[:top_nodes]
        selected_ids = {node_id for node_id, _ in ranked_nodes}

        scored_edges: List[Tuple[float, int, Dict[str, str]]] = []
        for edge in edges:
            if edge["source"] not in selected_ids and edge["target"] not in selected_ids:
                continue
            rel_lower = edge["label"].lower()
            rel_overlap = sum(1 for t in tokens if t in rel_lower)
            rel_hit_bonus = 0.4 if rel_overlap > 0 else 0.0
            score = node_scores.get(edge["source"], 0.0) + node_scores.get(edge["target"], 0.0) + rel_hit_bonus
            scored_edges.append((score, rel_overlap, edge))

        ranked_edge_items = sorted(scored_edges, key=lambda x: x[0], reverse=True)[:top_edges]
        ranked_edges = [edge for _, _, edge in ranked_edge_items]
        if not ranked_edges:
            return {
                "context": "",
                "matched_nodes": [],
                "matched_edges": [],
                "matched_communities": [],
                "best_edge_score": 0.0,
                "best_edge_overlap": 0,
                "graph_sources": graph_sources
            }

        matched_node_labels = []
        for node_id, _ in ranked_nodes:
            label = nodes_by_id.get(node_id)
            if label:
                matched_node_labels.append(label)

        relation_lines = []
        for edge in ranked_edges:
            source_label = nodes_by_id.get(edge["source"], edge["source"])
            target_label = nodes_by_id.get(edge["target"], edge["target"])
            relation_lines.append(f"{source_label} --{edge['label']}--> {target_label}")

        context_parts = []
        if relation_lines:
            context_parts.append("【Local Search】图谱关键关系:")
            context_parts.extend([f"- {line}" for line in relation_lines])
        context = "\n".join(context_parts)

        best_edge_score = float(ranked_edge_items[0][0]) if ranked_edge_items else 0.0
        best_edge_overlap = int(ranked_edge_items[0][1]) if ranked_edge_items else 0

        return {
            "context": context,
            "matched_nodes": matched_node_labels,
            "matched_edges": ranked_edges,
            "matched_communities": [],
            "best_edge_score": best_edge_score,
            "best_edge_overlap": best_edge_overlap,
            "graph_sources": graph_sources,
        }
