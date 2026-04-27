import json
import logging
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.model_config import get_model_config

router = APIRouter()
logger = logging.getLogger(__name__)

CHAT_DOCUMENT_DIR = "chat_units/chat_documents"
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")
KEYWORD_CACHE_FILE = Path(CHAT_DOCUMENT_DIR) / "keyword_top_cache.json"
LLM_BATCH_SIZE = 20


class KeywordTopRequest(BaseModel):
    session_id: Optional[str] = None
    username: Optional[str] = None
    top_n: Optional[int] = Field(default=10, ge=1, le=200)
    use_llm: bool = True
    per_question_max_keywords: int = Field(default=5, ge=1, le=20)


def _cache_key(request: KeywordTopRequest) -> str:
    return json.dumps(
        {
            "session_id": request.session_id,
            "username": request.username,
            "use_llm": request.use_llm,
            "per_question_max_keywords": request.per_question_max_keywords,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _load_daily_cache(cache_key: str) -> Optional[dict]:
    if not KEYWORD_CACHE_FILE.exists():
        return None
    try:
        with open(KEYWORD_CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        # 兼容旧格式：单条缓存
        if "entries" not in payload:
            if payload.get("cache_date") != today:
                return None
            if payload.get("cache_key") != cache_key:
                return None
            data = payload.get("data")
            return data if isinstance(data, dict) else None

        # 新格式：同一天多key缓存
        if payload.get("cache_date") != today:
            return None
        entries = payload.get("entries", {})
        if not isinstance(entries, dict):
            return None
        data = entries.get(cache_key)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"关键词缓存读取失败，忽略缓存: {e}")
        return None


def _save_daily_cache(cache_key: str, data: dict) -> None:
    try:
        KEYWORD_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        payload = {"cache_date": today, "entries": {}, "updated_at": datetime.now().isoformat()}

        if KEYWORD_CACHE_FILE.exists():
            try:
                with open(KEYWORD_CACHE_FILE, "r", encoding="utf-8") as f:
                    old_payload = json.load(f)
                if old_payload.get("cache_date") == today and isinstance(old_payload.get("entries"), dict):
                    payload["entries"] = old_payload["entries"]
            except Exception:
                pass

        payload["entries"][cache_key] = data
        payload["updated_at"] = datetime.now().isoformat()
        with open(KEYWORD_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"关键词缓存写入失败，不影响主流程: {e}")


def _slice_keywords_result(full_result: dict, top_n: Optional[int]) -> dict:
    top_keywords = full_result.get("top_keywords", [])
    if not isinstance(top_keywords, list):
        top_keywords = []
    sliced = top_keywords if top_n is None else top_keywords[:top_n]

    response = dict(full_result)
    response["top_keywords"] = sliced
    response["top_n"] = top_n
    response["total_available_keywords"] = len(top_keywords)
    response.pop("_full_keywords_cached", None)
    return response


def _iter_user_questions(session_id: Optional[str] = None, username: Optional[str] = None) -> List[str]:
    chat_dir = Path(CHAT_DOCUMENT_DIR)
    if not chat_dir.exists():
        return []

    def _normalize_owner(raw: str) -> str:
        value = str(raw or "").strip()
        if not value:
            return ""
        value = re.sub(r"[^\w.-]+", "_", value).strip("._")
        return value[:64] if value else ""

    normalized_username = str(username or "").strip()
    normalized_owner = _normalize_owner(normalized_username)

    questions: List[str] = []
    for file_path in chat_dir.rglob("*.json"):
        if file_path.name == "keyword_top_cache.json":
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions = data.get("chat_sessions", {})
            for sid, session_data in sessions.items():
                if session_id and sid != session_id:
                    continue
                if username:
                    session_user = str(
                        session_data.get("username")
                        or session_data.get("user_name")
                        or session_data.get("nickname")
                        or ""
                    ).strip()
                    owner_from_path = file_path.parent.name if file_path.parent != chat_dir else ""
                    if (
                        session_user != normalized_username
                        and _normalize_owner(session_user) != normalized_owner
                        and owner_from_path != normalized_owner
                    ):
                        continue
                for msg in session_data.get("history", []):
                    if msg.get("role") == "user":
                        content = (msg.get("content") or "").strip()
                        if content:
                            questions.append(content)
        except Exception as e:
            logger.warning(f"读取聊天文件失败，已跳过 {file_path}: {e}")
    return questions


def _normalize_keywords(items: List[str], limit: int) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for item in items:
        word = str(item).strip().lower()
        if len(word) < 2 or len(word) > 30:
            continue
        if word in seen:
            continue
        seen.add(word)
        normalized.append(word)
        if len(normalized) >= limit:
            break
    return normalized


def _extract_keywords_rule(question: str, limit: int) -> List[str]:
    stopwords = {
        "什么", "怎么", "请问", "一下", "这个", "那个", "可以", "帮我", "以及",
        "然后", "现在", "为什么", "如何", "是否", "一下子", "问题", "知识库",
        "接口", "实现", "功能", "需求", "进行"
    }
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_+\-#]+", question)
    tokens = [t for t in tokens if t not in stopwords]
    return _normalize_keywords(tokens, limit)


def _extract_keywords_llm_batch(questions: List[str], limit: int) -> Dict[int, List[str]]:
    if not questions:
        return {}

    indexed_questions = [{"id": idx + 1, "question": q} for idx, q in enumerate(questions)]
    model_config = get_model_config()
    prompt = f"""
你是关键词提取助手。请对输入的每条用户问题分别提取关键词（偏实体/术语）。

要求：
1) 仅返回JSON，不要返回其他说明文字
2) 每条问题关键词数量不超过 {limit} 个
3) 优先保留技术术语、数据结构名词、算法名词
4) 去掉无意义词（例如：请问、怎么、一下）
5) 必须保留并返回输入中的id，按每个id独立提取

输出格式：
{{
  "results": [
    {{"id": 1, "keywords": ["关键词1", "关键词2"]}},
    {{"id": 2, "keywords": ["关键词1"]}}
  ]
}}

输入问题列表（JSON）：
{json.dumps(indexed_questions, ensure_ascii=False)}
"""

    payload = {
        "model": model_config.kg_model,
        "prompt": prompt,
        "stream": False
    }
    response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"Ollama returned {response.status_code}")

    raw = response.json().get("response", "").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", raw, re.DOTALL)
        if not match:
            return []
        parsed = json.loads(match.group(1))

    if not isinstance(parsed, dict):
        return {}
    results = parsed.get("results", [])
    if not isinstance(results, list):
        return {}

    mapped: Dict[int, List[str]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        idx_raw = item.get("id")
        try:
            idx = int(idx_raw)
        except Exception:
            continue
        keywords = item.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        mapped[idx] = _normalize_keywords([str(x) for x in keywords], limit)
    return mapped


@router.post("/keyword-top")
async def keyword_top(request: KeywordTopRequest):
    """
    从聊天记录中提取用户问题关键词并统计TopN频次
    """
    key = _cache_key(request)
    cached = _load_daily_cache(key)
    if isinstance(cached, dict) and cached.get("_full_keywords_cached") is True:
        return _slice_keywords_result(cached, request.top_n)

    questions = _iter_user_questions(request.session_id, request.username)
    if not questions:
        raise HTTPException(status_code=404, detail="未找到可用的用户问题记录")

    counter: Counter = Counter()
    llm_fail_count = 0

    if request.use_llm:
        for start in range(0, len(questions), LLM_BATCH_SIZE):
            batch_questions = questions[start:start + LLM_BATCH_SIZE]
            try:
                batch_result = _extract_keywords_llm_batch(batch_questions, request.per_question_max_keywords)
            except Exception:
                llm_fail_count += len(batch_questions)
                batch_result = {}

            for idx, q in enumerate(batch_questions, start=1):
                keywords = batch_result.get(idx, [])
                if not keywords:
                    if batch_result:
                        llm_fail_count += 1
                    keywords = _extract_keywords_rule(q, request.per_question_max_keywords)
                counter.update(keywords)
    else:
        for q in questions:
            keywords = _extract_keywords_rule(q, request.per_question_max_keywords)
            counter.update(keywords)

    # 统一计算并缓存全量关键词频次，前端按top_n做截取返回
    all_items = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    full_result = {
        "session_id": request.session_id,
        "username": request.username,
        "total_questions": len(questions),
        "unique_keywords": len(counter),
        "llm_fail_count": llm_fail_count,
        "top_keywords": [{"keyword": k, "count": v} for k, v in all_items],
        "_full_keywords_cached": True,
    }
    _save_daily_cache(key, full_result)
    return _slice_keywords_result(full_result, request.top_n)
