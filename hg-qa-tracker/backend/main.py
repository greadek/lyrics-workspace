"""
多公司 QA/测试开发岗位跟踪系统 — FastAPI 后端
提供 REST API：岗位列表（按公司/项目/方向/级别/关键词过滤）、详情查询、刷新、
统计、数据源健康自检。所有 /api/* 需登录（见 auth.py）。
"""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    USING_DEFAULT_PASSWORD,
    check_credentials,
    clear_failures,
    client_ip,
    drop_session,
    get_session,
    is_locked,
    new_session,
    note_failure,
)
from fetcher import (
    fetch_all_jobs,
    fetch_job_detail,
    get_source_health,
    get_stats,
    _liveness,
)
from sources import COMPANIES


# ── 应用生命周期 ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预加载岗位数据（5 家公司；含 B站 playwright 启动约 5-10s）"""
    if USING_DEFAULT_PASSWORD:
        print(
            "[auth] 警告：正在使用默认口令 111111，"
            "建议设置 HG_ADMIN_PASSWORD 环境变量后重启"
        )
    print("[server] 启动中，预加载岗位数据...")
    try:
        jobs = await fetch_all_jobs()
        print(f"[server] 已加载 {len(jobs)} 个 QA 岗位")
    except Exception as e:
        print(f"[server] 预加载失败: {e}")
    yield


# docs/openapi 在根路径、不在 /api/ 前缀下，会被下面的登录守卫漏掉。
# 本服务只给 SPA 用，不需要 Swagger。
app = FastAPI(
    title="QA 岗位追踪 · 多公司",
    description="实时获取并整理鹰角网络/携程/B站/小红书/飞猪社招测试开发相关岗位要求",
    version="2.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ── 登录守卫 ──────────────────────────────────────────────────
# 用中间件而非 APIRouter(prefix="/api", dependencies=[...])：后者是"失败即开放"的，
# 未来任何一条写在 app 上的 /api/xxx 都会静默失去保护；中间件只写一次，无法遗漏。
# 注意 /api/health 必须精确相等，否则会连带放行 /api/health/sources。
EXEMPT = {("POST", "/api/auth/login"), ("GET", "/api/health")}


@app.middleware("http")
async def require_session(request: Request, call_next):
    path = request.url.path
    # 带尾斜杠，避免误伤 /apix；/、/static/* 一律放行
    if not (path == "/api" or path.startswith("/api/")):
        return await call_next(request)
    if (request.method, path) in EXEMPT:
        return await call_next(request)

    sess = get_session(request.cookies.get(SESSION_COOKIE))
    if sess is None:
        return JSONResponse(
            {"detail": "未登录或会话已过期"},
            status_code=401,
            headers={"WWW-Authenticate": "Cookie"},
        )
    request.state.user = sess["username"]
    return await call_next(request)


# ── 鉴权路由 ──────────────────────────────────────────────────
class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    # 必须设上界，否则超长口令会进比较逻辑
    password: str = Field(min_length=1, max_length=256)


# 用 def 而非 async def：凭据比较是同步逻辑，走 Starlette 线程池，不占用事件循环
@app.post("/api/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    """登录：校验通过后签发 session cookie"""
    ip = client_ip(request)
    if is_locked(ip):
        raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")
    if not check_credentials(body.username, body.password):
        note_failure(ip)
        # 不区分用户名/口令错，避免枚举
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    clear_failures(ip)
    response.set_cookie(
        SESSION_COOKIE,
        new_session(body.username),
        httponly=True,
        samesite="lax",
        path="/",
        max_age=int(SESSION_TTL.total_seconds()),
        # 本地 http 部署，不设 secure；若改用局域网 IP 访问也仍可工作
    )
    return {"ok": True, "username": body.username}


@app.get("/api/auth/me")
def me(request: Request):
    """当前登录用户（守卫已保证有会话）"""
    return {"username": request.state.user}


@app.post("/api/auth/logout")
def logout(request: Request):
    """登出：服务端销毁 session，同时带匹配属性删除 cookie"""
    drop_session(request.cookies.get(SESSION_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return resp


# ── API 路由 ──────────────────────────────────────────────────
@app.get("/api/jobs")
async def list_jobs(
    company: Optional[str] = Query(None, description="按公司筛选: 鹰角网络/携程/B站/小红书/飞猪（也接受 source 短 key）"),
    project: Optional[str] = Query(None, description="按项目筛选: 明日方舟, 终末地, 森空岛, UE项目..."),
    direction: Optional[str] = Query(None, description="按方向筛选: 系统向, 战斗向, 性能向, 工具向..."),
    level: Optional[str] = Query(None, description="按级别筛选: 资深/高级, 初中级, 管理"),
    search: Optional[str] = Query(None, description="关键词搜索（标题匹配）"),
    force_refresh: bool = Query(False, description="强制刷新缓存"),
):
    """获取 QA/测试开发岗位列表（跨公司）"""
    jobs = await fetch_all_jobs(force_refresh=force_refresh)

    if company:
        jobs = [j for j in jobs if j.get("source") == company or j.get("company") == company]
    if project:
        jobs = [j for j in jobs if project in j.get("project", "")]
    if direction:
        jobs = [j for j in jobs if direction in j.get("direction", "")]
    if level:
        jobs = [j for j in jobs if level in j.get("level", "")]
    if search:
        kw = search.lower()
        jobs = [
            j for j in jobs
            if kw in j.get("title", "").lower()
            or kw in j.get("direction", "").lower()
            or kw in j.get("project", "").lower()
        ]

    return {
        "total": len(jobs),
        "jobs": jobs,
        "stats": get_stats(jobs),
    }


@app.get("/api/jobs/{job_id}")
async def get_job_detail(job_id: str):
    """获取单个岗位的完整信息（含 JD 详情）"""
    jobs = await fetch_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")

    detail = await fetch_job_detail(job_id, job["title"], job.get("source", ""))
    job["detail"] = detail
    return job


@app.post("/api/jobs/refresh")
async def refresh_jobs():
    """强制刷新所有公司岗位数据"""
    jobs = await fetch_all_jobs(force_refresh=True)
    return {
        "total": len(jobs),
        "message": f"已刷新 {len(jobs)} 个岗位数据",
        "per_source": get_source_health(),
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


@app.get("/api/stats")
async def job_stats():
    """获取岗位统计信息"""
    jobs = await fetch_all_jobs()
    return get_stats(jobs)


@app.get("/api/projects")
async def list_projects():
    """获取所有筛选项（公司/项目/方向/级别）"""
    jobs = await fetch_all_jobs()
    return {
        "companies": [cfg["name"] for cfg in COMPANIES.values()],
        "projects": sorted(set(j.get("project", "未知") for j in jobs)),
        "directions": sorted(set(j.get("direction", "综合") for j in jobs)),
        "levels": sorted(set(j.get("level", "未知") for j in jobs)),
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "hg-qa-tracker"}


@app.get("/api/health/sources")
async def health_sources(live: bool = Query(False, description="是否执行实时可达性探测")):
    """数据源健康自查：默认读缓存（零网络）；live=1 时并发做轻量探测"""
    rows = get_source_health()
    live_map = None
    if live:
        results = await asyncio.gather(*(_liveness(k) for k in COMPANIES), return_exceptions=True)
        live_map = dict(zip(COMPANIES.keys(), results))
    return {"sources": rows, "live_reachable": live_map}


# ── 静态文件（前端） ──────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(frontend_dir):
    # 注意：此挂载免登录暴露整个 frontend/ 目录。当前只有 index.html（不含任何数据），
    # 所以无害 —— 不要把数据文件 / 导出文件放进 frontend/。
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))


# ── 启动入口 ──────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        # 只监听回环。cookie 无 secure、默认口令固定，绑 0.0.0.0 会把服务暴露到局域网。
        # 若确实需要局域网访问：改回 "0.0.0.0" 并务必先设 HG_ADMIN_PASSWORD 换掉默认口令。
        host="127.0.0.1",
        port=8765,
        # reload=True 会让每次保存文件都清空内存 session（开发期每次保存都需重新登录）
        reload=True,
        log_level="info",
    )
