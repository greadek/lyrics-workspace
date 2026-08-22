"""
多公司 QA/测试开发岗位数据编排器
- 聚合 sources/ 中各公司适配器
- per-company 缓存（30 分钟 TTL）+ 健康元数据（status/latency/error）
- 详情分发（官方来源直接切分，鹰角走爬取流程）
- 统计与健康自检
"""
import asyncio
import hashlib
import time
from datetime import datetime, timedelta

import httpx

from sources import COMPANIES, FETCH_TIMEOUTS
from sources.common import _SSL_CONTEXT, _is_qa_title, _split_jd_text

# ── 缓存 ──────────────────────────────────────────────────────
CACHE_TTL = timedelta(minutes=30)

# 每家公司一个缓存槽，兼作健康检查数据源
_company_cache: dict[str, dict] = {}
for _key in COMPANIES:
    _company_cache[_key] = {
        "jobs": None,          # 规范化岗位列表
        "details": {},         # md5(job_id) -> detail dict
        "fetched_at": None,    # 上次尝试抓取时间
        "status": "not_fetched",  # ok | error | not_fetched
        "last_error": None,
        "latency_ms": None,
        "last_success_at": None,
        "source_total": 0,     # 抓到的原始岗位数（过滤前）
    }

# 每家公司一把锁：避免 refresh 与启动预加载并发触发两个抓取（尤其 B站 playwright）
_company_locks: dict[str, asyncio.Lock] = {k: asyncio.Lock() for k in COMPANIES}

_last_fetch_at: datetime | None = None  # stats.fetched_at（最近一次任一家成功刷新）


def _cache_key(job_id: str) -> str:
    return hashlib.md5(job_id.encode()).hexdigest()


def _company_cache_valid(key: str) -> bool:
    fetched_at = _company_cache[key]["fetched_at"]
    if fetched_at is None:
        return False
    return datetime.now() - fetched_at < CACHE_TTL


# ── 单公司抓取包装器 ──────────────────────────────────────────
async def _fetch_company(key: str, force_refresh: bool = False) -> list[dict]:
    """抓取一家公司，缓存有效则直接返回；失败保留 stale 数据并记录错误"""
    slot = _company_cache[key]

    if not force_refresh and _company_cache_valid(key) and slot["jobs"]:
        return slot["jobs"]

    async with _company_locks[key]:
        # 锁内再检查一次缓存（等待期间可能已被刷新）
        if not force_refresh and _company_cache_valid(key) and slot["jobs"]:
            return slot["jobs"]

        slot["fetched_at"] = datetime.now()
        timeout = FETCH_TIMEOUTS.get(key, 30.0)
        start = time.perf_counter()

        try:
            jobs = await asyncio.wait_for(COMPANIES[key]["fetch"](), timeout=timeout)
            elapsed_ms = round((time.perf_counter() - start) * 1000)

            slot["jobs"] = jobs
            slot["status"] = "ok"
            slot["last_error"] = None
            slot["latency_ms"] = elapsed_ms
            slot["last_success_at"] = datetime.now()
            # 原始岗位数：从规范化岗位逆推不准确，仅记录当前 jobs 数作参考
            slot["source_total"] = len(jobs)
            global _last_fetch_at
            _last_fetch_at = datetime.now()
            return jobs

        except Exception as e:
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            slot["status"] = "error"
            slot["last_error"] = str(e)[:200]
            slot["latency_ms"] = elapsed_ms
            print(f"[fetcher] {key} 抓取失败: {e}")
            # 保留 stale jobs：降级为旧数据而非空列表
            if slot["jobs"]:
                return slot["jobs"]
            return []


# ── 聚合 ──────────────────────────────────────────────────────
async def fetch_all_jobs(force_refresh: bool = False) -> list[dict]:
    """抓取所有公司岗位，合并后按发布日期降序"""
    results = await asyncio.gather(
        *(_fetch_company(key, force_refresh) for key in COMPANIES)
    )

    all_jobs = []
    for jobs in results:
        all_jobs.extend(jobs)

    all_jobs.sort(key=lambda j: j.get("opened_at", ""), reverse=True)
    return all_jobs


# ── JD 详情 ──────────────────────────────────────────────────
async def fetch_job_detail(job_id: str, title: str, source: str) -> dict:
    """分发到各公司的详情生成逻辑"""
    slot = _company_cache.get(source)
    if not slot:
        return {
            "job_id": job_id, "title": title,
            "responsibilities": [], "requirements": [], "bonus": [],
            "source": "inferred",
        }

    cache_k = _cache_key(job_id)
    if cache_k in slot["details"]:
        return slot["details"][cache_k]

    # 找缓存中的岗位对象（官方来源需要其 description/requirement）
    job = next((j for j in (slot["jobs"] or []) if j.get("id") == job_id), None)

    detail = None
    if job is not None:
        try:
            detail = await COMPANIES[source]["detail"](job)
        except Exception as e:
            print(f"[fetcher] detail error {job_id}: {e}")

    if detail is None:
        detail = {
            "job_id": job_id, "title": title,
            "responsibilities": [], "requirements": [], "bonus": [],
            "source": "inferred",
        }

    slot["details"][cache_k] = detail
    return detail


# ── 统计 ──────────────────────────────────────────────────────
def get_stats(jobs: list[dict]) -> dict:
    """计算岗位统计"""
    companies = {}
    projects = {}
    directions = {}
    levels = {}

    for j in jobs:
        c = j.get("company", "未知")
        p = j.get("project", "未知")
        d = j.get("direction", "综合")
        l = j.get("level", "未知")
        companies[c] = companies.get(c, 0) + 1
        projects[p] = projects.get(p, 0) + 1
        directions[d] = directions.get(d, 0) + 1
        levels[l] = levels.get(l, 0) + 1

    return {
        "total": len(jobs),
        "by_company": companies,
        "by_project": projects,
        "by_direction": directions,
        "by_level": levels,
        "fetched_at": _last_fetch_at.isoformat() if _last_fetch_at else None,
    }


# ── 健康自检 ──────────────────────────────────────────────────
def get_source_health() -> list[dict]:
    """读取各数据源健康状态（纯缓存读取，零网络）"""
    rows = []
    for key, cfg in COMPANIES.items():
        slot = _company_cache[key]
        rows.append({
            "key": key,
            "name": cfg["name"],
            "status": slot["status"],
            "job_count": len(slot["jobs"]) if slot["jobs"] else 0,
            "source_total": slot["source_total"],
            "latency_ms": slot["latency_ms"],
            "last_error": slot["last_error"],
            "last_success_at": slot["last_success_at"].isoformat() if slot["last_success_at"] else None,
            "last_check_at": slot["fetched_at"].isoformat() if slot["fetched_at"] else None,
        })
    return rows


async def _liveness(key: str) -> bool:
    """轻量可达性探测（HTTP GET 站点根 / API）"""
    url = COMPANIES[key]["liveness_url"]
    try:
        async with httpx.AsyncClient(timeout=4.0, verify=_SSL_CONTEXT) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            return r.status_code < 500  # 200/301/302 视为可达
    except Exception:
        return False
