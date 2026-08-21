"""
鹰角网络 QA/测试开发 岗位跟踪系统 — FastAPI 后端
提供 REST API：岗位列表、详情查询、搜索过滤、统计
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from fetcher import fetch_qa_jobs, fetch_job_detail, fetch_all_with_details, get_stats


# ── 应用生命周期 ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预加载岗位数据"""
    print("[server] 启动中，预加载岗位数据...")
    try:
        jobs = await fetch_all_with_details()
        print(f"[server] 已加载 {len(jobs)} 个 QA 岗位")
    except Exception as e:
        print(f"[server] 预加载失败: {e}")
    yield


app = FastAPI(
    title="鹰角网络 QA 岗位追踪",
    description="实时获取并整理鹰角网络社招测试开发相关岗位要求",
    version="1.0.0",
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
    project: Optional[str] = Query(None, description="按项目筛选: 明日方舟, 终末地, 森空岛, UE项目"),
    direction: Optional[str] = Query(None, description="按方向筛选: 系统向, 战斗向, 性能向, 工具向..."),
    level: Optional[str] = Query(None, description="按级别筛选: 资深/高级, 初中级, 管理"),
    search: Optional[str] = Query(None, description="关键词搜索（标题匹配）"),
    force_refresh: bool = Query(False, description="强制刷新缓存"),
):
    """获取 QA/测试开发 岗位列表"""
    jobs = await fetch_qa_jobs(force_refresh=force_refresh)

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
    jobs = await fetch_qa_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")

    detail = await fetch_job_detail(job_id, job["title"])
    job["detail"] = detail
    return job


@app.post("/api/jobs/refresh")
async def refresh_jobs():
    """强制刷新所有岗位数据"""
    jobs = await fetch_all_with_details(force_refresh=True)
    return {
        "total": len(jobs),
        "message": f"已刷新 {len(jobs)} 个岗位数据",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


@app.get("/api/stats")
async def job_stats():
    """获取岗位统计信息"""
    jobs = await fetch_qa_jobs()
    return get_stats(jobs)


@app.get("/api/projects")
async def list_projects():
    """获取所有项目/方向/级别筛选项"""
    jobs = await fetch_qa_jobs()
    return {
        "projects": sorted(set(j.get("project", "未知") for j in jobs)),
        "directions": sorted(set(j.get("direction", "综合") for j in jobs)),
        "levels": sorted(set(j.get("level", "未知") for j in jobs)),
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "hg-qa-tracker"}


# ── 静态文件（前端） ──────────────────────────────────────────
import os
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
