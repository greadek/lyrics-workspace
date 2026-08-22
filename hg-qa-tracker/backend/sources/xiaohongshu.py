"""
小红书 QA/测试相关岗位数据获取适配器
- 北森 ATS 接口 POST /websiterecruit/position/pageQueryPosition
- recruitType 为小写 "social"；搜索字段为 positionName
- 岗位返回 duty(职责)/qualification(要求)，直接作为官方 JD
"""
import httpx

from .common import _SSL_CONTEXT, _is_qa_title, infer_direction, infer_level, _split_jd_text

# ── API 配置 ──────────────────────────────────────────────────
XHS_BASE = "https://job.xiaohongshu.com"
PAGE_QUERY_URL = f"{XHS_BASE}/websiterecruit/position/pageQueryPosition"
REFERER = f"{XHS_BASE}/"
SOURCE = "xiaohongshu"
COMPANY_NAME = "小红书"
PAGE_SIZE = 50

# 搜索关键词（服务端按 positionName 过滤，减小请求量）
KEYWORDS = ["测试", "测试开发", "QA", "质量", "测开", "质检"]


async def fetch_jobs() -> list[dict]:
    """获取小红书 QA/测试相关社招岗位（多关键词 + 分页 + 去重 + QA 过滤）"""
    all_raw: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=20.0, verify=_SSL_CONTEXT,
                                 headers={"Referer": REFERER}) as client:
        for kw in KEYWORDS:
            page_no = 1
            while True:
                body = _build_body(page_no, kw)
                try:
                    resp = await client.post(PAGE_QUERY_URL, json=body)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    print(f"[xiaohongshu] API error kw={kw} page={page_no}: {e}")
                    break

                if data.get("statusCode") != 200:
                    print(f"[xiaohongshu] API error kw={kw}: {data.get('alertMsg')}")
                    break

                result = data.get("data") or {}
                items = result.get("list") or []
                if not items:
                    break

                for item in items:
                    pid = item.get("positionId")
                    if pid is not None:
                        all_raw[pid] = item

                total_page = int(result.get("totalPage") or 1)
                if page_no >= total_page:
                    break
                page_no += 1

    # 按标题做 QA 过滤
    jobs = []
    for item in all_raw.values():
        title = item.get("positionName", "")
        if not _is_qa_title(title):
            continue
        jobs.append(_normalize(item))

    jobs.sort(key=lambda j: j.get("opened_at", ""), reverse=True)
    return jobs


def _build_body(page_no: int, keyword: str) -> dict:
    """构造 pageQueryPosition 请求体（已验证：recruitType 小写 + positionName 搜索）"""
    return {
        "recruitType": "social",
        "pageNo": page_no,
        "pageSize": PAGE_SIZE,
        "positionName": keyword,
        "projectId": "",
        "departmentId": [],
        "jobCategory": [],
        "workCity": [],
        "degree": [],
        "workYear": [],
    }


def _normalize(raw: dict) -> dict:
    """标准化小红书岗位数据"""
    title = raw.get("positionName", "")
    workplace = raw.get("workplace", "") or ""
    # 工作地多为 "上海·杨浦区"，取首段
    city = workplace.split("·")[0].strip() if workplace else ""

    return {
        "id": f"{SOURCE}:{raw.get('positionId', '')}",
        "mj_code": "",
        "title": title,
        "commitment": "全职",
        "project": raw.get("jobProjectName") or "通用/未指定",
        "direction": infer_direction(title),
        "level": infer_level(title),
        "category": raw.get("jobType", ""),
        "department_id": None,
        "location": {
            "country": "中国",
            "city": city,
            "address": workplace,
        },
        "opened_at": raw.get("publishTime", ""),
        "updated_at": "",
        "apply_url": f"{XHS_BASE}/position/{raw.get('positionId', '')}",
        "is_subsidiary": False,
        "description": raw.get("duty", ""),
        "requirement": raw.get("qualification", ""),
        "company": COMPANY_NAME,
        "source": SOURCE,
        "raw": raw,
    }


async def fetch_detail(job: dict) -> dict:
    """小红书岗位详情：从 duty + qualification 切分（官方来源，无网络请求）"""
    text = "\n".join(filter(None, [job.get("description", ""), job.get("requirement", "")]))
    detail = _split_jd_text(text, job.get("title", ""))
    detail["job_id"] = job["id"]
    detail["title"] = job["title"]
    detail["source"] = "official"
    return detail
