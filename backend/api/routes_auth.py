"""Authentication & user management routes."""

import hmac
import hashlib
import json
import re
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from config import settings
from models.database import (
    create_user,
    delete_user,
    get_user_by_id,
    get_user_by_username,
    list_users,
    update_user,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _b64e(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return urlsafe_b64decode(s + "=" * pad)


def create_token(user_id: str, username: str, role: str) -> str:
    header = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64e(
        json.dumps(
            {"sub": user_id, "username": username, "role": role, "exp": int(time.time()) + settings.jwt_expiry_seconds}
        ).encode()
    )
    sig = _b64e(hmac.new(settings.jwt_secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def create_download_token(user_id: str, path: str, ttl_seconds: int = 120) -> str:
    header = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64e(
        json.dumps(
            {
                "sub": user_id,
                "scope": "download",
                "path": path,
                "exp": int(time.time()) + ttl_seconds,
            }
        ).encode()
    )
    sig = _b64e(hmac.new(settings.jwt_secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_token(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b, payload_b, sig_b = parts
    expected = _b64e(hmac.new(settings.jwt_secret.encode(), f"{header_b}.{payload_b}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig_b):
        return None
    try:
        payload = json.loads(_b64d(payload_b))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
    download_token: Annotated[str | None, Query()] = None,
) -> dict:
    """Resolve authenticated user from Authorization header OR ?token= query.

    Query-param fallback exists so browser-driven downloads (window.open) and
    WebSocket connections can pass credentials without setting headers.
    """
    raw_token: str | None = None
    token_source = "session"
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization[7:]
    elif token:
        raw_token = token
    elif download_token:
        raw_token = download_token
        token_source = "download"
    if not raw_token:
        raise HTTPException(status_code=401, detail="未登入")
    payload = decode_token(raw_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 無效或已過期")
    if token_source == "download":
        if payload.get("scope") != "download" or payload.get("path") != request.url.path:
            raise HTTPException(status_code=401, detail="下載票證無效")
    elif payload.get("scope") == "download":
        raise HTTPException(status_code=401, detail="下載票證不可用於一般 API")
    user = get_user_by_id(payload["sub"])
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="帳號已停用")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理員權限")
    return user


def user_display_label(user: dict) -> str:
    """Return the authoritative reviewer label for audit records."""
    return (user.get("display_name") or user.get("username") or "unknown").strip()


# ── Public ───────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


class DownloadTokenRequest(BaseModel):
    path: str


class DownloadTokenResponse(BaseModel):
    token: str
    expires_in: int


DOWNLOAD_TOKEN_TTL_SECONDS = 120
DOWNLOAD_TOKEN_ALLOWED_PATTERNS = (
    re.compile(r"^/ws/compare/[^/]+$"),
    re.compile(r"^/api/compare/[^/]+/pdf/(old|new)$"),
    re.compile(r"^/api/compare/[^/]+/crop/d\d{3,}/(old|new)$"),
    re.compile(r"^/api/compare/[^/]+/snapshots/[^/\\]+$"),
    re.compile(r"^/api/compare/[^/]+/snapshots/download\.zip$"),
    re.compile(r"^/api/export/[^/]+/(report|pdf|excel|log|log-csv|log-txt)$"),
    re.compile(r"^/api/archive/files/[^/]+/(old_pdf|new_pdf|annotated_pdf)$"),
)
DOWNLOAD_TOKEN_ALLOWED_PATHS = {
    "/api/projects/all/comparisons/export",
}


def _is_allowed_download_path(path: str) -> bool:
    if "?" in path or "://" in path:
        return False
    return path in DOWNLOAD_TOKEN_ALLOWED_PATHS or any(pattern.match(path) for pattern in DOWNLOAD_TOKEN_ALLOWED_PATTERNS)


@router.post("/login")
def login(req: LoginRequest):
    user = get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="帳號已停用")
    token = create_token(user["id"], user["username"], user["role"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
        },
    }


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
    }


@router.post("/download-token", response_model=DownloadTokenResponse)
def issue_download_token(req: DownloadTokenRequest, user: dict = Depends(get_current_user)):
    path = req.path.strip()
    if not _is_allowed_download_path(path):
        raise HTTPException(status_code=400, detail="不允許產生此路徑的下載票證")
    return {
        "token": create_download_token(user["id"], path, DOWNLOAD_TOKEN_TTL_SECONDS),
        "expires_in": DOWNLOAD_TOKEN_TTL_SECONDS,
    }


# ── Admin: user management ───────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    username: str
    display_name: str
    password: str
    role: Literal["admin", "reviewer"] = "reviewer"


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    password: str | None = None
    role: Literal["admin", "reviewer"] | None = None
    is_active: bool | None = None


@router.get("/users")
def admin_list_users(_admin: dict = Depends(require_admin)):
    return list_users()


@router.post("/users")
def admin_create_user(req: CreateUserRequest, _admin: dict = Depends(require_admin)):
    existing = get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=409, detail="帳號已存在")
    return create_user(req.username, req.display_name, req.password, req.role)


@router.put("/users/{user_id}")
def admin_update_user(user_id: str, req: UpdateUserRequest, _admin: dict = Depends(require_admin)):
    if not get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="使用者不存在")
    update_user(user_id, display_name=req.display_name, password=req.password, role=req.role, is_active=req.is_active)
    return {"ok": True}


@router.delete("/users/{user_id}")
def admin_delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不可刪除自己的帳號")
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="使用者不存在")
    return {"ok": True}
