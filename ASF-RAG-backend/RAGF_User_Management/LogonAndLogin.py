from contextlib import closing

from fastapi import APIRouter, HTTPException, Form, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import pymysql
import jwt

from datetime import datetime, timedelta
import hashlib
import logging
from pydantic import BaseModel
from typing import Optional

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = APIRouter()

# 定义数据模型
class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: Optional[str] = "student"

class UserLogin(BaseModel):
    account: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = "student"

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login/login")


import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 数据库配置 - 从环境变量中读取
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', 'cg040206'),
    'database': os.getenv('DB_NAME', 'mysql'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4')
}


def get_db_connection():
    """
    获取数据库连接
    """
    print(DB_CONFIG)
    return pymysql.connect(**DB_CONFIG)


def normalize_role(role: Optional[str]) -> str:
    value = str(role or "").strip().lower()
    if value in ("teacher", "student"):
        return value
    return "student"


def create_user_table():
    """
    创建用户表（如果不存在则创建）
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 创建数据库（如果不存在）
        cursor.execute("CREATE DATABASE IF NOT EXISTS rag_user_db")
        cursor.execute("USE rag_user_db")

        # 创建用户表
        cursor.execute('''CREATE TABLE IF NOT EXISTS user(
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) NOT NULL UNIQUE,
            email VARCHAR(255) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'student',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # 兼容旧库：补充username/role字段并回填
        cursor.execute("SHOW COLUMNS FROM user LIKE 'username'")
        username_column = cursor.fetchone()
        if not username_column:
            cursor.execute("ALTER TABLE user ADD COLUMN username VARCHAR(100)")
            cursor.execute("UPDATE user SET username=email WHERE username IS NULL OR username=''")
            cursor.execute("ALTER TABLE user MODIFY COLUMN username VARCHAR(100) NOT NULL")
            cursor.execute("ALTER TABLE user ADD UNIQUE KEY uk_user_username (username)")

        cursor.execute("SHOW COLUMNS FROM user LIKE 'role'")
        role_column = cursor.fetchone()
        if not role_column:
            cursor.execute("ALTER TABLE user ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'student'")
        cursor.execute("UPDATE user SET role='student' WHERE role IS NULL OR role=''")
        
        conn.commit()
        logger.info("用户表验证完成")
        return True

    except Exception as e:
        logger.error(f"数据库操作出错: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# 初始化时创建表
create_user_table()



def create_userData_table():
    """
    创建用户数据表（如果不存在则创建）
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 确保使用正确的数据库
        cursor.execute("USE rag_user_db")
        
        # 创建用户资料表，包含社交平台字段
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_profile(
           user_id INT PRIMARY KEY,
           name VARCHAR(100),
           signature TEXT,
           social_media VARCHAR(500),
           avatar VARCHAR(255),
           FOREIGN KEY(user_id) REFERENCES user(id) ON DELETE CASCADE
        )''')
        conn.commit()
        logger.info("用户数据表验证完成")
        return True
    except Exception as e:
        logger.error(f"数据库操作出错: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



create_userData_table()


# 创建用户
def create_user(username: str, email: str, password: str, role: Optional[str] = "student") -> bool:
    """
    创建用户
    """
    conn = None
    try:
        # 对密码进行哈希处理（数据库里要加密）
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        print(username, email)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 确保使用正确的数据库
        cursor.execute("USE rag_user_db")

        # 检查用户名或邮箱是否已存在
        cursor.execute("SELECT * FROM user WHERE email = %s OR username = %s", (email, username))
        if cursor.fetchone():
            logger.warning("用户名或邮箱已存在")
            return False

        # 插入新用户
        normalized_role = normalize_role(role)
        cursor.execute("INSERT INTO user (username, email, password, role) VALUES (%s, %s, %s, %s)",
                       (username, email, hashed_password, normalized_role))
        conn.commit()

        # 验证插入是否成功
        cursor.execute("SELECT * FROM user WHERE email = %s", (email,))
        if cursor.fetchone():
            logger.info("用户创建成功")
            return True
        return False

    except Exception as e:
        logger.info(f"数据库操作出错: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# 用户登录验证
def user_login(account: str, password: str) -> bool:
    """
    用户登录验证
    """
    conn = None
    try:
        # 对密码进行哈希处理
        hashed_password = hashlib.sha256(password.encode()).hexdigest()

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 确保使用正确的数据库
        cursor.execute("USE rag_user_db")

        cursor.execute("SELECT * FROM user WHERE (email = %s OR username = %s) AND password = %s",
                       (account, account, hashed_password))
        user = cursor.fetchone()

        return user is not None

    except Exception as e:
        logger.error(f"数据库操作出错: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# 生成JWT令牌
# ... existing code ...

# 生成JWT令牌
def get_user_role(email: str) -> str:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("USE rag_user_db")
        cursor.execute("SELECT role FROM user WHERE email = %s", (email,))
        result = cursor.fetchone()
        if result and result[0]:
            return normalize_role(result[0])
    except Exception as e:
        logger.warning(f"获取用户角色失败，使用默认student: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass
    return "student"


def get_user_by_account(account: str) -> Optional[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("USE rag_user_db")
        cursor.execute("SELECT username, email, role FROM user WHERE email = %s OR username = %s", (account, account))
        result = cursor.fetchone()
        if not result:
            return None
        return {
            "username": result[0],
            "email": result[1],
            "role": normalize_role(result[2]),
        }
    except Exception as e:
        logger.error(f"查询用户信息失败: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def authenticate_user(email: str, role: Optional[str] = None) -> str:
    """
    生成JWT令牌
    """
    secret_key = 'secret'
    # 到时候改成环境变量拿
    resolved_role = normalize_role(role or get_user_role(email))
    payload = {
        "sub": email,
        "role": resolved_role,
        "exp": datetime.utcnow() + timedelta(hours=1)  # 令牌过期时间
    }
    try:
        # 尝试使用新版本PyJWT的编码方法
        return jwt.encode(payload, secret_key, algorithm="HS256")
    except AttributeError:
        # 如果上面的方法失败，尝试其他方式
        try:
            from jwt import encode as jwt_encode
            return jwt_encode(payload, secret_key, algorithm="HS256")
        except (ImportError, AttributeError):
            # 最后的备选方案
            raise Exception("无法生成JWT令牌，请检查PyJWT库的安装")

# 验证JWT令牌
def verify_jwt(token: str) -> dict:
    """
    验证JWT令牌
    """
    secret_key = "secret"  # 应与生成时使用的密钥一致
    try:
        # 尝试使用新版本PyJWT的解码方法
        return jwt.decode(token, secret_key, algorithms=["HS256"])
    except AttributeError:
        # 如果上面的方法失败，尝试其他方式
        try:
            from jwt import decode as jwt_decode
            return jwt_decode(token, secret_key, algorithms=["HS256"])
        except (ImportError, AttributeError):
            return {"error": "无法解码JWT令牌"}

# ... existing code ...




# 向user_profile.db注入初始化数据

def init_profile(email: str) -> bool:
    """
    初始化用户数据表 (修复版)
    """
    # 第一部分：获取用户ID
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("USE rag_user_db")
        
        # 检查表结构
        cursor.execute("DESCRIBE user")
        columns = [column[0] for column in cursor.fetchall()]
        
        if 'id' not in columns:
            logger.error(f"用户表结构不正确，缺少id列。当前列: {columns}")
            return False
            
        # 查询用户ID
        cursor.execute("SELECT id FROM user WHERE email = %s", (email,))
        result = cursor.fetchone()

        if not result:
            logger.error(f"用户不存在: {email}")
            return False

        user_id = result[0]
        
        # 关闭游标和连接
        cursor.close()
        conn.close()
        conn = None  # 标记连接已关闭
        
    except Exception as e:
        logger.error(f"获取用户ID失败: {e}")
        return False
    finally:
        # 只有当连接存在且未关闭时才尝试关闭
        if conn:
            try:
                conn.close()
            except:
                pass  # 忽略关闭连接时的错误

    # 第二部分：创建用户配置
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("USE rag_user_db")
        
        # 确保表存在（包含社交平台字段）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id INT NOT NULL UNIQUE,
                name VARCHAR(100) DEFAULT '新用户',
                signature TEXT DEFAULT '这个人很懒，什么也没写',
                social_media VARCHAR(500) DEFAULT '',  -- 社交平台信息
                avatar VARCHAR(255) DEFAULT 'https://pic3.zhimg.com/80/v2-71152904edf11db5c8885548393ace6a_720w.webp',
                FOREIGN KEY(user_id) REFERENCES user(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id)
            )
        """)

        # 插入初始化数据（包含社交平台字段）
        cursor.execute("""
            INSERT IGNORE INTO user_profile (user_id, name, signature, social_media, avatar)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, "初始化内容", "初始化签名", "", "https://pic3.zhimg.com/80/v2-71152904edf11db5c8885548393ace6a_720w.webp"))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"创建用户配置失败: {e}")
        return False
    finally:
        # 只有当连接存在且未关闭时才尝试关闭
        if conn:
            try:
                conn.close()
            except:
                pass  # 忽略关闭连接时的错误


def safe_db_operation(email, role: Optional[str] = "student"):
    token = authenticate_user(email, role)
    init_profile(email)
    return token

# 注册接口 - 支持JSON和表单数据
@router.post("/api/register", response_model=dict)
async def register_user(user: UserCreate):
    """
    用户注册接口 (JSON格式)
    """
    role = normalize_role(user.role)
    if create_user(user.username, user.email, user.password, role):
        token = safe_db_operation(user.email, role)
        return {
            "status": "success",
            "message": "用户注册成功",
            "token": token,
            "role": role
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="用户注册失败（可能邮箱已存在）"
        )

@router.post("/api/register/form", response_model=dict)
async def register_user_form(username: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form("student")):
    """
    用户注册接口 (表单格式)
    """
    normalized_role = normalize_role(role)
    if create_user(username, email, password, normalized_role):
        token = safe_db_operation(email, normalized_role)
        return {
            "status": "success",
            "message": "用户注册成功",
            "token": token,
            "role": normalized_role
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="用户注册失败（可能邮箱已存在）"
        )

# 登录接口 - 支持多种方式
@router.post("/api/login", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    用户登录接口 (OAuth2标准格式)
    """
    if user_login(form_data.username, form_data.password):  # OAuth2中username字段作为登录账号（用户名或邮箱）
        user_info = get_user_by_account(form_data.username)
        if not user_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authenticate_user(user_info["email"], user_info["role"])
        return {"access_token": token, "token_type": "bearer", "role": user_info["role"]}
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.post("/api/login/json", response_model=dict)
async def login_user_json(user: UserLogin):
    """
    用户登录接口 (JSON格式)
    """
    if user_login(user.account, user.password):
        user_info = get_user_by_account(user.account)
        if not user_info:
            raise HTTPException(
                status_code=401,
                detail="用户名或密码错误"
            )
        token = authenticate_user(user_info["email"], user_info["role"])
        return {
            "status": "success",
            "message": "登录成功",
            "token": token,
            "role": user_info["role"]
        }
    else:
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误"
        )

@router.post("/api/login/form", response_model=dict)
async def login_user_form(account: str = Form(...), password: str = Form(...)):
    """
    用户登录接口 (表单格式)
    """
    if user_login(account, password):
        user_info = get_user_by_account(account)
        if not user_info:
            raise HTTPException(
                status_code=401,
                detail="用户名或密码错误"
            )
        token = authenticate_user(user_info["email"], user_info["role"])
        return {
            "status": "success",
            "message": "登录成功",
            "token": token,
            "role": user_info["role"]
        }
    else:
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误"
        )

# 获取当前用户信息接口
@router.get("/api/users/me", response_model=dict)
async def read_users_me(token: str = Depends(oauth2_scheme)):
    """
    获取当前用户信息
    """
    result = verify_jwt(token)
    if "error" in result:
        raise HTTPException(
            status_code=401,
            detail=result["error"]
        )
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("USE rag_user_db")
        
        # 查询用户信息
        cursor.execute("SELECT id, email, role, created_at FROM user WHERE email = %s", (result["sub"],))
        user = cursor.fetchone()
        
        if user:
            return {
                "status": "success",
                "user": {
                    "id": user[0],
                    "email": user[1],
                    "role": normalize_role(user[2]),
                    "created_at": user[3]
                }
            }
        else:
            raise HTTPException(
                status_code=404,
                detail="用户不存在"
            )
    except Exception as e:
        logger.error(f"获取用户信息出错: {e}")
        raise HTTPException(
            status_code=500,
            detail="服务器内部错误"
        )
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# 验证令牌接口
@router.post("/api/verify-token", response_model=dict)
async def verify_token_endpoint(token: str = Form(...)):
    """
    验证JWT令牌
    """
    result = verify_jwt(token)
    if "error" in result:
        raise HTTPException(
            status_code=401,
            detail=result["error"]
        )
    return {
        "status": "success",
        "message": "令牌有效",
        "data": result
    }

# 退出登录接口
@router.post("/api/logout", response_model=dict)
async def logout_user():
    """
    用户退出登录
    注意：JWT是无状态的，服务端无法直接使其失效
    这里只是返回成功消息，实际的token清理需要客户端处理
    """
    return {
        "status": "success",
        "message": "退出登录成功"
    }