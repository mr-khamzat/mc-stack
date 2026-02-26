import os
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel
from ..auth import verify_password, hash_password, create_token, require_admin, _decode

router = APIRouter(prefix="/api/auth", tags=["auth"])

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_HASH = hash_password(os.getenv("ADMIN_PASSWORD", "changeme"))

COOKIE_NAME = "rack_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest, response: Response):
    if req.username != ADMIN_USER or not verify_password(req.password, ADMIN_HASH):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(req.username, role="admin")
    # Set HttpOnly cookie so nginx auth_request can validate netmap access
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return {"token": token, "username": req.username, "role": "admin"}


@router.get("/me")
def me(payload: dict = Depends(require_admin)):
    return {"username": payload["sub"], "role": payload["role"]}


@router.get("/check-cookie")
def check_cookie(request: Request):
    """Used by nginx auth_request to validate netmap access via session cookie."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        raise HTTPException(status_code=401, detail="No session")
    try:
        _decode(cookie)
        return {"ok": True}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
