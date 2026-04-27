from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from functools import lru_cache
import os
from pathlib import Path
from dotenv import load_dotenv
import json
import asyncio
import re

from fastapi.responses import StreamingResponse
import io
import contextlib


# 导入RAG_M原有的核心组件
import sys
project_root = str(Path(__file__).parent)
sys.path.append(project_root)

from src.rag.rag_pipeline import RAGPipeline
from src.rag.graph_retriever import LocalGraphRAGRetriever
from src.vectorstore.vector_store import VectorStoreManager
from models.model_config import get_model_config

load_dotenv()

router = APIRouter()


def _tokenize_query(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    tokens = re.findall(r"[\u4e00-\u9fff]{2,12}|[a-z0-9_]{2,}", lowered)
    # keep order, dedupe
    return list(dict.fromkeys(tokens))


def _dedupe_docs(docs: list) -> list:
    seen = set()
    unique = []
    for doc in docs:
        metadata = getattr(doc, "metadata", {}) or {}
        source = metadata.get("source", metadata.get("path", metadata.get("file_path", "")))
        text = (getattr(doc, "page_content", "") or "").strip()
        signature = f"{source}|{text[:160]}"
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(doc)
    return unique


def _hybrid_retrieve_docs(vectorstore, query: str, top_k: int = 12, fetch_k: int = 60) -> list:
    """
    Precision-first retrieval:
    1) similarity search for exact relevance
    2) MMR for diversity补充
    3) lexical fallback over all stored chunks
    """
    candidates = []

    try:
        candidates.extend(vectorstore.similarity_search(query, k=max(top_k, 12)))
    except Exception:
        pass

    try:
        candidates.extend(
            vectorstore.max_marginal_relevance_search(
                query, k=max(8, top_k // 2), fetch_k=fetch_k, lambda_mult=0.75
            )
        )
    except Exception:
        pass

    # lexical fallback: if query tokens appear in chunk, include it
    tokens = _tokenize_query(query)
    try:
        doc_map = getattr(getattr(vectorstore, "docstore", None), "_dict", None)
        if isinstance(doc_map, dict):
            lexical_hits = []
            for doc in doc_map.values():
                content = (getattr(doc, "page_content", "") or "").lower()
                if not content:
                    continue
                hit = sum(1 for t in tokens if t in content)
                if hit > 0:
                    lexical_hits.append((hit, doc))
            lexical_hits.sort(key=lambda x: x[0], reverse=True)
            candidates.extend([doc for _, doc in lexical_hits[:top_k]])
    except Exception:
        pass

    return _dedupe_docs(candidates)[:top_k]


def _normalize_source_item(source: dict, index: int) -> dict:
    """
    Normalize heterogeneous source metadata into a stable frontend contract.
    """
    if not isinstance(source, dict):
        return {
            "doc_id": f"D{index}",
            "source": str(source),
            "source_path": str(source),
            "page": None
        }

    raw_source = (
        source.get("source")
        or source.get("path")
        or source.get("file_path")
        or source.get("file")
        or source.get("filename")
        or source.get("name")
        or f"Document {index}"
    )
    source_text = str(raw_source)
    source_name = os.path.basename(source_text) or source_text

    page_raw = source.get("page")
    if page_raw is None:
        page_raw = source.get("page_number")
    if page_raw is None:
        page_raw = source.get("page_index")

    normalized_page = None
    if page_raw is not None:
        try:
            normalized_page = int(page_raw)
        except (TypeError, ValueError):
            normalized_page = None

    normalized = dict(source)
    normalized.update({
        "doc_id": source.get("doc_id", f"D{index}"),
        "source": source_name,
        "source_path": source_text,
        "page": normalized_page
    })
    return normalized


def _dedupe_source_items(sources: list[dict]) -> list[dict]:
    """
    Dedupe sources for UI display:
    - if page exists: unique by (source_path, page)
    - if page is missing: unique by source_path
    """
    deduped = []
    seen = set()
    for item in sources:
        source_path = str(item.get("source_path") or item.get("source") or "")
        page = item.get("page")
        key = (source_path, page) if page is not None else (source_path, None)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def should_apply_graph_context(query: str, graph_result: dict) -> tuple[bool, str]:
    """
    Gate graph context injection to avoid low-quality KG hurting RAG answers.
    """
    mode = os.getenv("GRAPH_CONTEXT_MODE", "strict").lower()
    if mode == "off":
        return False, "GRAPH_CONTEXT_MODE=off"
    if mode == "on":
        return True, "GRAPH_CONTEXT_MODE=on"

    matched_edges = graph_result.get("matched_edges", []) or []
    best_edge_score = float(graph_result.get("best_edge_score", 0.0) or 0.0)
    best_edge_overlap = int(graph_result.get("best_edge_overlap", 0) or 0)
    context = (graph_result.get("context", "") or "").strip()
    if not context:
        return False, "empty graph context"

    # strict mode: only rely on top similar triple quality.
    if len(matched_edges) < 1:
        return False, "no matched triples"
    if best_edge_score < 1.2:
        return False, "best triple score too low"
    if best_edge_overlap < 1:
        tokens = _tokenize_query(query)
        if tokens:
            return False, "best triple lexical overlap too low"
    return True, "top triple quality passed"

class QueryRequest(BaseModel):
    query: str
    docs_dir: str = None  # 可选的文件夹路径

class IngestRequest(BaseModel):
    docs_dir: str


class IngestAndQueryRequest(BaseModel):
    docs_dir: str
    query: str
    



@contextlib.contextmanager
def capture_stdout():
    stdout_buffer = io.StringIO()
    original_stdout = sys.stdout
    
    # 创建一个双重输出的类
    class DualOutput:
        def __init__(self, original, buffer):
            self.original = original
            self.buffer = buffer
            
        def write(self, text):
            self.original.write(text)
            self.buffer.write(text)
            
        def flush(self):
            self.original.flush()
            self.buffer.flush()
            
        def isatty(self):
            # 模拟终端属性，返回False表示不是终端
            return False
    
    sys.stdout = DualOutput(original_stdout, stdout_buffer)
    try:
        yield stdout_buffer
    finally:
        sys.stdout = original_stdout



@lru_cache()
def get_rag_pipeline(vectorstore_path: str = None):
    """初始化RAG管道"""
    # 使用传入的路径或环境变量中的路径
    vectorstore_path = vectorstore_path or os.getenv("VECTORSTORE_PATH")
    if not vectorstore_path:
        raise ValueError("Vector store path not provided and VECTORSTORE_PATH not set in environment")
    
    vector_store_manager = VectorStoreManager()
    vectorstore = vector_store_manager.load_vectorstore(
        vectorstore_path,
        trust_source=True
    )
    print(f"初始化RAG管道，使用模型: {os.getenv('MODEL')}，向量存储路径: {vectorstore_path}")
    return RAGPipeline(os.getenv("MODEL"), vectorstore)



@router.post("/RAG_query")
async def process_query(query_body: QueryRequest):
    """RAG智能查询接口 - 支持指定文件夹路径进行查询，以流式方式返回结果"""
    
    async def generate():
        try:
            yield f"data: 开始处理查询: {query_body.query}\n\n"
            
            # 统一使用一个VectorStoreManager实例
            vector_store_manager = VectorStoreManager(docs_dir=query_body.docs_dir)
            
            # 确定向量存储路径
            if query_body.docs_dir:
                vectorstore_path = os.path.join(query_body.docs_dir, "vectorstore")
                yield f"data: 使用自定义向量存储路径: {vectorstore_path}\n\n"
                
                if not os.path.exists(vectorstore_path):
                    error_msg = f"向量存储路径不存在: {vectorstore_path}"
                    yield f"data: ERROR: {error_msg}\n\n"
                    raise HTTPException(status_code=404, detail=f"Vector store not found at {vectorstore_path}")
                
                yield "data: 正在加载向量存储...\n\n"
                vectorstore = vector_store_manager.load_vectorstore(
                    vectorstore_path,
                    trust_source=True
                )
                yield "data: 向量存储加载完成\n\n"
            else:
                yield "data: 使用默认向量存储\n\n"
                vectorstore_path = os.getenv("VECTORSTORE_PATH")
                vectorstore = vector_store_manager.load_vectorstore(
                    vectorstore_path,
                    trust_source=True
                )
                yield "data: 默认向量存储加载完成\n\n"
            
            # 初始化RAG管道
            yield "data: 初始化RAG管道...\n\n"
            model_config = get_model_config()
            llm_model = os.getenv("MODEL") or model_config.llm_model
            kg_model = model_config.kg_model
            yield f"data: 当前RAG模型: {llm_model}\n\n"
            yield f"data: 当前知识图谱模型: {kg_model}\n\n"
            rag = RAGPipeline(llm_model, vectorstore, retriever_k=6, retriever_fetch_k=30)
            yield "data: RAG管道初始化完成\n\n"
            
            # 处理查询
            yield "data: 开始处理查询...\n\n"
            
            # 获取相关文档
            yield "data: 正在检索相关文档...\n\n"
            docs = _hybrid_retrieve_docs(
                vectorstore=vectorstore,
                query=query_body.query,
                top_k=12,
                fetch_k=60
            )
            yield f"data: 找到 {len(docs)} 个相关文档\n\n"

            # 输出命中文档预览，便于排查“文档明明有内容却没答出来”的问题
            preview_count = min(3, len(docs))
            if preview_count > 0:
                yield "data: 命中文档片段预览:\n\n"
                for idx in range(preview_count):
                    snippet = docs[idx].page_content.replace("\n", " ").strip()[:120]
                    yield f"data: {idx + 1}. {snippet}\n\n"
            
            # 处理查询并获取结果
            graph_context = ""
            graph_sources = []
            graph_node_count = 0
            graph_edge_count = 0
            graph_community_count = 0
            graph_best_edge_score = 0.0
            graph_best_edge_overlap = 0
            graph_applied = False
            graph_gate_reason = "graph not evaluated"
            if query_body.docs_dir:
                yield "data: 正在执行图谱检索（GraphRAG）...\n\n"
                graph_retriever = LocalGraphRAGRetriever(query_body.docs_dir)
                graph_result = graph_retriever.retrieve(query_body.query)
                graph_context = graph_result.get("context", "")
                graph_sources = graph_result.get("graph_sources", [])
                graph_node_count = len(graph_result.get("matched_nodes", []))
                graph_edge_count = len(graph_result.get("matched_edges", []))
                graph_community_count = len(graph_result.get("matched_communities", []))
                graph_best_edge_score = float(graph_result.get("best_edge_score", 0.0) or 0.0)
                graph_best_edge_overlap = int(graph_result.get("best_edge_overlap", 0) or 0)
                graph_applied, graph_gate_reason = should_apply_graph_context(query_body.query, graph_result)
                if graph_context and graph_applied:
                    yield f"data: GraphRAG命中三元组 {graph_edge_count} 条（最佳得分 {graph_best_edge_score:.2f}）\n\n"
                    preview_lines = graph_context.splitlines()[:8]
                    for line in preview_lines:
                        yield f"data: {line}\n\n"
                elif graph_context and not graph_applied:
                    yield f"data: 图谱证据未通过门控，降级为纯向量RAG（原因: {graph_gate_reason}）\n\n"
                    graph_context = ""
                else:
                    yield "data: GraphRAG未命中有效图谱证据，将仅使用向量检索结果\n\n"

            try:
                result = rag.process_query_with_documents(query_body.query, docs, extra_context=graph_context)
            except Exception as rag_error:
                error_text = str(rag_error)
                if "502" in error_text or "Bad Gateway" in error_text:
                    yield "data: 检测到Ollama 502，自动降级重试（减少检索上下文）...\n\n"
                    fallback_rag = RAGPipeline(llm_model, vectorstore, retriever_k=1, retriever_fetch_k=2)
                    fallback_docs = docs[:3]
                    result = fallback_rag.process_query_with_documents(query_body.query, fallback_docs, extra_context=graph_context)
                    yield "data: 降级重试成功\n\n"
                else:
                    raise

            normalized_sources = [
                _normalize_source_item(source, i)
                for i, source in enumerate(result.get("sources", []), 1)
            ]
            normalized_sources = _dedupe_source_items(normalized_sources)
            
            # 分段返回回答内容
            # 假设我们要按段落分割
            paragraphs = result["answer"].split('\n\n')
            
            yield "data: 正在生成回答...\n\n"
            for paragraph in paragraphs:
                if paragraph.strip():
                    yield f"data: {paragraph.strip()}\n\n"
                    # 可选：添加短暂延迟以模拟流式输出效果
                    await asyncio.sleep(0.1)
            
            # 返回来源信息
            yield "data: 参考来源:\n\n"
            for source in normalized_sources:
                doc_id = source.get("doc_id", "D?")
                source_text = source.get("source", "unknown")
                yield f"data: {doc_id}. {source_text}\n\n"
            
            # 发送完整结果作为JSON以便客户端可以获取结构化数据
            final_result = {
                "answer": result["answer"],
                "sources": normalized_sources,
                "vectorstore_path": vectorstore_path,
                "graph_sources": graph_sources,
                "graph_stats": {
                    "matched_nodes": graph_node_count,
                    "matched_edges": graph_edge_count,
                    "matched_communities": graph_community_count,
                    "best_edge_score": graph_best_edge_score,
                    "best_edge_overlap": graph_best_edge_overlap,
                    "applied_to_answer": graph_applied,
                    "gate_reason": graph_gate_reason
                },
            }
            yield f"data: COMPLETE: {json.dumps(final_result, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            error_msg = f"查询处理失败: {str(e)}\n{error_trace}"
            yield f"data: ERROR: {error_msg}\n\n"
            print(f"[ERROR] {error_msg}")
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )



@router.post("/ingest")
async def ingest_documents(ingest_body: IngestRequest):
    """文档导入接口 - 替代原来的ingest_documents.py功能"""
    def generate():
        with capture_stdout() as stdout_buffer:
            print(f"Starting document ingestion from directory: {ingest_body.docs_dir}")
            try:
                from src.ingestion.document_loader import DocumentLoader
                from src.vectorstore.vector_store import VectorStoreManager
                
                # 使用知识库目录中的配置
                vector_store_manager = VectorStoreManager(docs_dir=ingest_body.docs_dir)
                documents = []

                # 动态确定向量存储路径
                vectorstore_path = ingest_body.docs_dir + "/vectorstore"
                print(f"Using vector store path: {vectorstore_path}")
                yield f"data: Using vector store path: {vectorstore_path}\n\n"
                
                # 检查目录是否存在
                if not os.path.exists(ingest_body.docs_dir):
                    print(f"Directory does not exist: {ingest_body.docs_dir}")
                    yield f"data: Directory does not exist: {ingest_body.docs_dir}\n\n"
                    raise ValueError(f"Directory does not exist: {ingest_body.docs_dir}")
                
                # 初始化加载器和向量存储管理器
                print("Initializing DocumentLoader")
                yield "data: Initializing DocumentLoader\n\n"
                #loader = DocumentLoader()
                loader = DocumentLoader(docs_dir=ingest_body.docs_dir)
                #vector_store_manager = VectorStoreManager() #删除默认项
                documents = []
                
                # 统计信息
                processed_count = 0
                skipped_count = 0
                error_count = 0
                
                # 首先遍历并处理所有文件
                print("Walking through directory to process files")
                yield "data: Walking through directory to process files\n\n"
                
                for root, dirs, files in os.walk(ingest_body.docs_dir):
                    
                    # 🔧 新增：在遍历前过滤掉需要忽略的目录
                    dirs[:] = [d for d in dirs if d not in loader.IGNORED_DIRECTORIES]
                    
                    # 跳过已经是vectorstore目录的情况
                    if 'vectorstore' in os.path.basename(root):
                        print(f"Skipping vectorstore directory: {root}")
                        yield f"data: Skipping vectorstore directory: {root}\n\n"
                        continue
                    
                    
                    
                    print(f"Found {len(files)} files in {root}")
                    yield f"data: Found {len(files)} files in {root}\n\n"
                    
                    for file in files:
                        file_path = os.path.join(root, file)
                        
                        try:
                            # 🔧 新增：检查是否应该跳过文件
                            should_skip, skip_reason = loader.should_skip_file(file_path)
                            if should_skip:
                                print(f"Skipping file: {file} ({skip_reason})")
                                yield f"data: Skipping file: {file} ({skip_reason})\n\n"
                                skipped_count += 1
                                continue
                            
                            print(f"Processing file: {file_path}")
                            yield f"data: Processing file: {file_path}\n\n"
                            
                            docs = loader.load_document(file_path)
                            print(f"Successfully loaded {len(docs)} document chunks from {file_path}")
                            yield f"data: Successfully loaded {len(docs)} document chunks from {file_path}\n\n"
                            documents.extend(docs)
                            processed_count += 1
                            
                        except ValueError as ve:
                            # 处理跳过文件的情况（由load_document内部抛出）
                            if "Skipped file" in str(ve):
                                print(f"Skipping file: {file} ({str(ve)})")
                                yield f"data: Skipping file: {file} ({str(ve)})\n\n"
                                skipped_count += 1
                            else:
                                print(f"Unsupported file type {file_path}: {str(ve)}")
                                yield f"data: Unsupported file type {file_path}: {str(ve)}\n\n"
                                error_count += 1
                            continue
                        except Exception as e:
                            print(f"Error processing {file_path}: {str(e)}")
                            yield f"data: Error processing {file_path}: {str(e)}\n\n"
                            error_count += 1
                            continue
                
                # 🔧 新增：输出处理统计
                print(f"Processing summary: {processed_count} processed, {skipped_count} skipped, {error_count} errors")
                yield f"data: Processing summary: {processed_count} processed, {skipped_count} skipped, {error_count} errors\n\n"
                
                # 检查是否有文档被成功处理
                if not documents:
                    print("No documents were processed successfully")
                    yield "data: No documents were processed successfully\n\n"
                    raise ValueError("No documents were processed successfully")
                
                # 所有文档处理完成后，创建向量存储
                print(f"Creating vector store with {len(documents)} document chunks")
                yield f"data: Creating vector store with {len(documents)} document chunks\n\n"
                vector_store_manager.create_vectorstore(documents, vectorstore_path)
                print(f"Vector store successfully created and saved to {vectorstore_path}")
                yield f"data: Vector store successfully created and saved to {vectorstore_path}\n\n"
                
                # 发送最终结果
                result = {
                    "message": f"Successfully ingested {len(documents)} document chunks",
                    "documents_count": len(documents),
                    "vectorstore_path": vectorstore_path,
                    "stats": {
                        "processed": processed_count,
                        "skipped": skipped_count,
                        "errors": error_count
                    }
                }
                print(f"Successfully ingested {len(documents)} document chunks")
                yield f"data: {json.dumps(result)}\n\n"
                
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                error_msg = f"Document ingestion failed: {str(e)}\n{error_trace}"
                print(f"ERROR: {error_msg}")
                yield f"data: ERROR: {error_msg}\n\n"
                raise HTTPException(status_code=500, detail=error_msg)
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.post("/ingest_and_query")
async def ingest_and_query(request: IngestAndQueryRequest):
    """
    组合接口：先对指定知识库目录执行文档向量化，再基于最新向量库执行RAG查询
    """
    try:
        from src.ingestion.document_loader import DocumentLoader
        from src.vectorstore.vector_store import VectorStoreManager

        if not os.path.exists(request.docs_dir):
            raise HTTPException(status_code=404, detail=f"Directory does not exist: {request.docs_dir}")
        if not os.path.isdir(request.docs_dir):
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {request.docs_dir}")

        vector_store_manager = VectorStoreManager(docs_dir=request.docs_dir)
        loader = DocumentLoader(docs_dir=request.docs_dir)

        vectorstore_path = os.path.join(request.docs_dir, "vectorstore")
        documents = []
        processed_count = 0
        skipped_count = 0
        error_count = 0

        for root, dirs, files in os.walk(request.docs_dir):
            dirs[:] = [d for d in dirs if d not in loader.IGNORED_DIRECTORIES]
            if "vectorstore" in os.path.basename(root):
                continue

            for file in files:
                file_path = os.path.join(root, file)
                try:
                    should_skip, skip_reason = loader.should_skip_file(file_path)
                    if should_skip:
                        print(f"Skipping file: {file} ({skip_reason})")
                        skipped_count += 1
                        continue

                    docs = loader.load_document(file_path)
                    documents.extend(docs)
                    processed_count += 1
                except ValueError as ve:
                    if "Skipped file" in str(ve):
                        skipped_count += 1
                    else:
                        print(f"Unsupported file type {file_path}: {str(ve)}")
                        error_count += 1
                except Exception as e:
                    print(f"Error processing {file_path}: {str(e)}")
                    error_count += 1

        if not documents:
            raise HTTPException(
                status_code=400,
                detail="No documents were processed successfully. Please check docs_dir and file formats."
            )

        # 执行向量化（覆盖更新当前知识库向量索引）
        vector_store_manager.create_vectorstore(documents, vectorstore_path)

        # 立即加载最新向量库并执行查询
        vectorstore = vector_store_manager.load_vectorstore(vectorstore_path, trust_source=True)
        model_config = get_model_config()
        llm_model = os.getenv("MODEL") or model_config.llm_model
        rag = RAGPipeline(llm_model, vectorstore, retriever_k=6, retriever_fetch_k=30)

        result = rag.process_query(request.query)
        return {
            "message": "Ingest and query completed successfully",
            "query": request.query,
            "answer": result["answer"],
            "sources": result["sources"],
            "vectorstore_path": vectorstore_path,
            "documents_count": len(documents),
            "stats": {
                "processed": processed_count,
                "skipped": skipped_count,
                "errors": error_count
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"ingest_and_query failed: {str(e)}\n{error_trace}")



@router.post("/init")
async def init_project():
    """项目初始化接口 - 替代原来的setup.py功能"""
    try:
        # 导入初始化逻辑
        from src.scripts.init_project import init_project as init_func
        
        init_func()
        return {"message": "Project initialized successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project initialization failed: {str(e)}")

@router.get("/health")
async def rag_health_check():
    """RAG服务健康检查"""
    try:
        # 简单检查关键组件是否可用
        model = os.getenv("MODEL")
        vectorstore_path = os.getenv("VECTORSTORE_PATH")
        
        return {
            "status": "healthy", 
            "service": "RAG Query Service",
            "model": model,
            "vectorstore_path": vectorstore_path,
            "vectorstore_exists": os.path.exists(vectorstore_path) if vectorstore_path else False
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
