import io
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path  # 🔧 添加缺失的导入
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, List

# 创建路由
router = APIRouter()

# 🔧 修复：使用统一的目录路径
CHAT_DOCUMENT_DIR = "chat_units/chat_documents"

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeleteSessionRequest(BaseModel):
    sessionId: str
    username: str


def _normalize_owner(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="缺少用户名")
    value = re.sub(r"[^\w.-]+", "_", value).strip("._")
    if not value:
        raise HTTPException(status_code=400, detail="用户名无效")
    return value[:64]

@router.delete("/delete-session")  # 🔧 修复：改为DELETE方法，路径简化
async def delete_session(request: DeleteSessionRequest):
    """删除指定的对话会话"""
    try:
        session_id = request.sessionId
        
        if not session_id:
            raise HTTPException(status_code=400, detail="缺少会话ID")
        
        owner = _normalize_owner(request.username)
        chat_dir = Path(CHAT_DOCUMENT_DIR) / owner
        
        if not chat_dir.exists():
            logger.warning(f"对话目录不存在: {chat_dir}")
            raise HTTPException(status_code=404, detail="对话目录不存在")
        
        # 🔧 新逻辑：搜索包含指定会话的文件
        session_found = False
        
        for file_path in chat_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 检查文件中是否包含目标会话
                chat_sessions = data.get("chat_sessions", {})
                if session_id in chat_sessions:
                    # 删除指定会话
                    del chat_sessions[session_id]
                    session_found = True
                    
                    # 如果文件不再包含任何会话，删除整个文件
                    if not chat_sessions:
                        os.remove(file_path)
                        logger.info(f"文件已删除: {file_path.name}")
                    else:
                        # 保存更新后的文件
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        logger.info(f"会话已从文件中删除: {file_path.name}")
                    
                    break  # 找到并处理完毕，退出循环
                    
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败 {file_path}: {str(e)}")
            except Exception as e:
                logger.error(f"处理文件失败 {file_path}: {str(e)}")
        
        if not session_found:
            raise HTTPException(status_code=404, detail=f"会话 {session_id} 未找到")
        
        # 🔧 修复：返回与前端期望一致的响应格式
        return JSONResponse(content={
            "status": "success",
            "message": f"会话 {session_id} 已成功删除"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"删除会话失败: {str(e)}"
        )

# 🔧 保持向后兼容的旧接口（可选）
@router.post("/delete-chat-document")
async def delete_chat_document_legacy(request: dict):
    """旧版删除接口，保持向后兼容"""
    session_id = request.get("sessionId")
    username = request.get("username") or request.get("user_name") or request.get("nickname")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少会话ID")
    if not username:
        raise HTTPException(status_code=400, detail="缺少用户名")
    
    # 转换为新的请求格式并调用新接口
    new_request = DeleteSessionRequest(sessionId=session_id, username=username)
    return await delete_session(new_request)
