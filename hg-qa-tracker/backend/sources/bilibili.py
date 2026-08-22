"""
B站 QA/测试相关岗位数据获取适配器
- B站社招接口 /api/srs/position/positionList 有反爬（ajSessionId 绑定浏览器会话），
  只能通过 Playwright 在页面上下文内先取 csrf token，再带反爬 headers POST。
- 用 sync_playwright + asyncio.to_thread 在 worker 线程运行，与 FastAPI 事件循环隔离。
"""
import asyncio
import random
import time

import httpx

from .common import _SSL_CONTEXT, _is_qa_title, infer_direction, infer_level, _split_jd_text

# ── API 配置 ──────────────────────────────────────────────────
SITE = "https://jobs.bilibili.com/social"
CSRF_URL = "/api/auth/v1/csrf/token"
LIST_URL = "https://jobs.bilibili.com/api/srs/position/positionList"
SOURCE = "bilibili"
COMPANY_NAME = "B站"
PAGE_SIZE = 50

# 反爬必需的 headers
X_APPKEY = "ops.ehr-api.auth"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://jobs.bilibili.com",
    "Referer": "https://jobs.bilibili.com/social",
}


async def fetch_jobs() -> list[dict]:
    """获取 B站 QA/测试相关社招岗位（Playwright 页面环境抓取）"""
    return await asyncio.to_thread(_fetch_jobs_sync)


def _fetch_jobs_sync() -> list[dict]:
    """同步抓取（在 to_thread 线程内运行 sync_playwright）"""
    from playwright.sync_api import sync_playwright

    all_raw: dict[int, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
            )
            page = context.new_page()
            # 加载页面：建立 buvid cookies + 反爬指纹
            page.goto(SITE, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)

            # lunar-id：反爬 header，格式 lunar-{毫秒时间戳}-{13位随机数}，可自生成（已验证服务器只校验格式）
            lunar = f"lunar-{int(time.time() * 1000)}-{random.randint(10**12, 10**13 - 1)}"

            # 在页面上下文内取 csrf token（绑定浏览器会话）。
            # 必须带 X-UserType + lunar-id，否则返回 code=-101 "ajSessionId不能为空"。
            csrf = page.evaluate(
                """async (args) => {
                    const r = await fetch(args.url, {
                        headers: { 'X-AppKey': args.appkey, 'X-UserType': '2', 'lunar-id': args.lunar }
                    });
                    const j = await r.json();
                    return j.data;
                }""",
                {"url": CSRF_URL, "appkey": X_APPKEY, "lunar": lunar},
            )
            if not csrf:
                print("[bilibili] 获取 csrf token 失败")
                return []

            fetch_headers = {
                **HEADERS,
                "X-AppKey": X_APPKEY,
                "X-UserType": "2",
                "X-Csrf": csrf,
                "X-Channel": "social",
                "lunar-id": lunar,
            }

            page_num = 1
            total = 0
            while True:
                payload = {
                    "pageSize": PAGE_SIZE,
                    "pageNum": page_num,
                    "positionName": "",
                    "postCode": [],
                    "postCodeList": [],
                    "workLocationList": [],
                    "workTypeList": ["3"],
                    "positionTypeList": ["3"],
                    "deptCodeList": [],
                    "recruitType": 0,
                    "practiceTypes": [],
                    "onlyHotRecruit": 0,
                }
                result = page.evaluate(
                    """async (args) => {
                        const r = await fetch(args.url, {
                            method: 'POST',
                            headers: args.headers,
                            body: JSON.stringify(args.body),
                        });
                        return await r.json();
                    }""",
                    {"url": LIST_URL, "headers": fetch_headers, "body": payload},
                )

                if result.get("code") != 0:
                    print(f"[bilibili] API error page={page_num}: {result.get('message')}")
                    break

                data = result.get("data") or {}
                items = data.get("list") or []
                if not items:
                    break

                for item in items:
                    jid = item.get("id")
                    if jid is not None:
                        all_raw[jid] = item

                total = int(data.get("total") or 0)
                if page_num * PAGE_SIZE >= total or len(all_raw) >= total:
                    break
                page_num += 1
        finally:
            browser.close()

    # 按标题做 QA 过滤
    jobs = []
    for item in all_raw.values():
        title = item.get("positionName", "")
        if not _is_qa_title(title):
            continue
        jobs.append(_normalize(item))

    jobs.sort(key=lambda j: j.get("opened_at", ""), reverse=True)
    return jobs


def _normalize(raw: dict) -> dict:
    """标准化 B站岗位数据"""
    title = raw.get("positionName", "")
    work_location = raw.get("workLocation") or ""
    city = "、".join(work_location) if isinstance(work_location, list) else str(work_location)

    return {
        "id": f"{SOURCE}:{raw.get('id', '')}",
        "mj_code": "",
        "title": title,
        "commitment": "全职",
        "project": "通用/未指定",
        "direction": infer_direction(title),
        "level": infer_level(title),
        "category": raw.get("positionTypeName", ""),
        "department_id": None,
        "location": {
            "country": "中国",
            "city": city,
            "address": city,
        },
        "opened_at": raw.get("pushTime", ""),
        "updated_at": "",
        "apply_url": f"{SITE}/position/{raw.get('id', '')}",
        "is_subsidiary": False,
        "description": raw.get("positionDescription", ""),
        "requirement": "",
        "company": COMPANY_NAME,
        "source": SOURCE,
        "raw": raw,
    }


async def fetch_detail(job: dict) -> dict:
    """B站岗位详情：从 positionDescription 切分（官方来源，无网络请求）"""
    detail = _split_jd_text(job.get("description", ""), job.get("title", ""))
    detail["job_id"] = job["id"]
    detail["title"] = job["title"]
    detail["source"] = "official"
    return detail
