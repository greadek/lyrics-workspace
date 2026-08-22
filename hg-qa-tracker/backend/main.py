"""
多公司 QA/测试开发岗位跟踪系统 — FastAPI 后端
提供 REST API：岗位列表（按公司/项目/方向/级别/关键词过滤）、详情查询、刷新、
统计、数据源健康自检
"""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    """启动时预加载岗位数据（4 家公司；含 B站 playwright 启动约 5-10s）"""
    print("[server] 启动中，预加载岗位数据...")
    try:
        jobs = await fetch_all_jobs()
        print(f"[server] 已加载 {len(jobs)} 个 QA 岗位")
    except Exception as e:
        print(f"[server] 预加载失败: {e}")
    yield


app = FastAPI(
    title="QA 岗位追踪 · 多公司",
    description="实时获取并整理鹰角网络/携程/B站/小红书社招测试开发相关岗位要求",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API 路由 ──────────────────────────────────────────────────
@app.get("/api/jobs")
async def list_jobs(
    company: Optional[str] = Query(None, description="按公司筛选: 鹰角网络/携程/B站/小红书（也接受 source 短 key）"),
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
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))


# ── 启动入口 ──────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        log_level="info",
    )
