from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain_ollama.llms import OllamaLLM
#from langchain.vectorstores import FAISS
from langchain_community.vectorstores import FAISS
from langchain.prompts import PromptTemplate
import requests
from typing import List, Any, Dict

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from models.model_config import get_model_config


class RAGPipeline:
    def __init__(
        self,
        llm_model: str = None,
        vectorstore: FAISS = None,
        retriever_k: int = 6,
        retriever_fetch_k: int = 30
    ):
        # 如果没有提供模型名称，则从统一配置中获取
        if llm_model is None:
            model_config = get_model_config()
            llm_model = model_config.llm_model
            print(f"==================Using default LLM model: {llm_model}")
        
        self.llm_model = llm_model
        self.retriever_k = retriever_k
        self.retriever_fetch_k = retriever_fetch_k
        self.ollama_api_url = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")
        
        self.llm = OllamaLLM(model=llm_model)
        self.vectorstore = vectorstore
        self.qa_chain = self._create_qa_chain()

    def _create_qa_chain(self):
        """Create the retrieval QA chain with custom prompt"""
        prompt_template = """你是知识管理助手，专门回答基于文档的技术问题。

    规则：
    1. 基于提供的上下文回答
    2. 如果信息不足，说现有文档没有提及信息不足的这一块内容，然后给出自己知道的一些信息，说供参考
    3. 回答时引用相关文档片段
    4. 用户没有声明回答所用的语言时用中文回答，否则用所声明语言回答
    5. 快速而准确的回答是关键，且回答尽量完整
    6. 如果用户问题中包含代码片段，尽量提供相关代码示例
    7. 如果用户问题中包含公式，尽量提供相关公式示例
    8. 如果用户问题中包含表格，尽量提供相关表格示例
    9. 与上下文无关的提问，指出其与上下文无关，并提供从别处了解的相关信息

    上下文信息：
    {context}

    用户问题：{question}

    回答："""

        PROMPT = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        # 创建检索器
        retriever = self.vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": self.retriever_k,
                "fetch_k": self.retriever_fetch_k,
                "lambda_mult": 0.5
            }
        )
        
        return RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={
                "prompt": PROMPT,
                "verbose": True
            }
        )

    def _build_prompt(self, query: str, context: str) -> str:
        return f"""你是知识管理助手，专门回答基于文档的技术问题。

    规则：
    1. 基于提供的上下文回答
    2. 如果信息不足，说现有文档没有提及信息不足的这一块内容，然后给出自己知道的一些信息，说供参考
    3. 回答时引用相关文档片段
    4. 用户没有声明回答所用的语言时用中文回答，否则用所声明语言回答
    5. 快速而准确的回答是关键，且回答尽量完整
    6. 如果用户问题中包含代码片段，尽量提供相关代码示例
    7. 如果用户问题中包含公式，尽量提供相关公式示例
    8. 如果用户问题中包含表格，尽量提供相关表格示例
    9. 与上下文无关的提问，指出其与上下文无关，并提供从别处了解的相关信息

    上下文信息：
    {context}

    用户问题：{query}

    回答："""

    def _build_grounded_prompt(self, query: str, context: str) -> str:
        return f"""你是知识管理助手。请严格基于提供的证据片段回答问题。

规则：
1) 只能依据证据片段作答，不要编造未出现的事实。
2) 每个关键结论后都要追加证据编号，格式如 [D1]、[D2]。
3) 若证据不足，明确说明“现有片段无法定位该信息”，并给出用户应补充的关键词。
4) 优先给出与问题最直接相关的定义、步骤、公式或代码要点。
5) 用户没有声明回答所用的语言时用中文回答，否则用所声明语言回答。

证据片段：
{context}

用户问题：{query}

回答："""

    def _call_ollama(self, prompt: str) -> str:
        payload = {
            "model": self.llm_model,
            "prompt": prompt,
            "stream": False
        }
        response = requests.post(self.ollama_api_url, json=payload, timeout=300)
        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama call failed with status {response.status_code}: {response.text[:300]}"
            )
        return response.json().get("response", "")

    def _build_context_from_docs(self, docs: List[Any], max_docs: int = 8, max_chars_each: int = 900) -> str:
        lines = []
        for idx, doc in enumerate(docs[:max_docs], 1):
            content = (getattr(doc, "page_content", "") or "").strip().replace("\n", " ")
            snippet = content[:max_chars_each]
            metadata = getattr(doc, "metadata", {}) or {}
            source_text = metadata.get("source", metadata.get("path", metadata.get("file_path", "unknown")))
            lines.append(f"[D{idx}] source={source_text}\n{snippet}")
        return "\n\n".join(lines)

    def _process_query_with_http_fallback(self, query: str, extra_context: str = "") -> dict:
        """
        Fallback path that calls Ollama HTTP API directly.
        This mirrors the knowledge-graph module call style.
        """
        retriever = self.vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 4, "fetch_k": 20, "lambda_mult": 0.5}
        )
        docs = retriever.get_relevant_documents(query)
        context = "\n\n".join([doc.page_content for doc in docs])[:10000]
        if extra_context:
            context = f"{context}\n\n[图谱补充上下文]\n{extra_context}"
        prompt = self._build_prompt(query, context)
        answer = self._call_ollama(prompt)
        return {
            "answer": answer,
            "sources": [doc.metadata for doc in docs]
        }

    def process_query_with_documents(self, query: str, docs: List[Any], extra_context: str = "") -> Dict[str, Any]:
        """
        Use caller-provided retrieval results to generate grounded answers.
        """
        context = self._build_context_from_docs(docs)
        if extra_context:
            context = f"{context}\n\n[图谱补充上下文]\n{extra_context}"
        prompt = self._build_grounded_prompt(query, context)
        answer = self._call_ollama(prompt)

        sources = []
        for idx, doc in enumerate(docs, 1):
            metadata = getattr(doc, "metadata", {}) or {}
            source_meta = dict(metadata)
            source_meta["doc_id"] = f"D{idx}"
            sources.append(source_meta)
        return {"answer": answer, "sources": sources}


    def process_query(self, query: str, extra_context: str = "") -> dict:
        """
        Process a query through the RAG pipeline
        
        Returns:
            dict: Contains response text and source documents
        """
        try:
            # When external graph context is provided, use HTTP path to inject it into prompt context directly.
            # if extra_context:
            #     return self._process_query_with_http_fallback(query, extra_context=extra_context)

            result = self.qa_chain({"query": query})
            return {
                "answer": result["result"],
                "sources": [doc.metadata for doc in result["source_documents"]]
            }
        except Exception as e:
            message = str(e)
            if "502" in message or "Bad Gateway" in message:
                return self._process_query_with_http_fallback(query, extra_context=extra_context)
            raise Exception(f"Error processing query: {message}")