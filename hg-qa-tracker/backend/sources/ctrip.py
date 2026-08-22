"""
携程 QA/测试相关岗位数据获取适配器
- 通过携程自建招聘 API POST /api/hrrecruit/getJobAd 搜索关键词
- requirements 字段为 HTML，用 BeautifulSoup 解析为纯文本
"""
import re

import httpx
from bs4 import BeautifulSoup

from .common import _SSL_CONTEXT, _is_qa_title, infer_direction, infer_level, _split_jd_text

# ── API 配置 ──────────────────────────────────────────────────
CTRIP_BASE = "https://careers.ctrip.com"
GET_JOB_AD_URL = f"{CTRIP_BASE}/api/hrrecruit/getJobAd"
REFERER = f"{CTRIP_BASE}/"
SOURCE = "ctrip"
COMPANY_NAME = "携程"
PAGE_SIZE = 10  # pager.index/size 为字符串

# 搜索关键词（服务端支持按 keyword 过滤，减小请求量）
KEYWORDS = ["测试", "测试开发", "QA", "质量", "测开", "质检"]


async def fetch_jobs() -> list[dict]:
    """获取携程 QA/测试相关在招岗位（多关键词搜索 + 去重 + QA 过滤）"""
    all_raw: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=20.0, verify=_SSL_CONTEXT,
                                 headers={"Referer": REFERER}) as client:
        for kw in KEYWORDS:
            index = 1
            while True:
                body = _build_body(index, kw)
                try:
                    resp = await client.post(GET_JOB_AD_URL, json=body)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    print(f"[ctrip] API error kw={kw} index={index}: {e}")
                    break

                ret = data.get("retValue") or {}
                items = ret.get("recruitJobAdList") or []
                if not items:
                    break

                for item in items:
                    if item.get("id"):
                        all_raw[item["id"]] = item

                total = int(ret.get("total") or 0)
                if index * PAGE_SIZE >= total:
                    break
                index += 1

    # 按标题做 QA 过滤（服务端关键词搜索可能不精确）
    jobs = []
    for item in all_raw.values():
        title = item.get("jobTitle", "")
        if not _is_qa_title(title):
            continue
        jobs.append(_normalize(item))

    jobs.sort(key=lambda j: j.get("opened_at", ""), reverse=True)
    return jobs


def _build_body(index: int, keyword: str) -> dict:
    """构造 getJobAd 请求体（已验证的载荷结构）"""
    return {
        "condition": {
            "fromId": [],
            "keyword": keyword,
            "kind": [],
            "country": [],
            "city": [],
            "bucode": [],
            "jobFamilyCode": [],
            "jobFamilyGroupCode": [],
            "category": 1,
        },
        "pager": {"index": str(index), "size": str(PAGE_SIZE)},
        "head": {"language": "zh_CN", "version": "1"},
    }


def _normalize(raw: dict) -> dict:
    """标准化携程岗位数据"""
    raw_title = raw.get("jobTitle", "")
    # 去掉标题尾部的 （…）(MJ…) 显示后缀
    title = re.sub(r"（.+?）\(MJ\d+\)$", "", raw_title).strip() or raw_title

    requirements_html = raw.get("requirements", "") or ""
    text = _strip_html(requirements_html)

    return {
        "id": f"{SOURCE}:{raw.get('id', '')}",
        "mj_code": raw.get("fromId", ""),
        "title": title,
        "commitment": "全职",
        "project": "通用/未指定",
        "direction": infer_direction(title),
        "level": infer_level(title),
        "category": "携程社招",
        "department_id": None,
        "location": {
            "country": "中国",
            "city": raw.get("cityName") or raw.get("city", ""),
            "address": "",
        },
        "opened_at": raw.get("publishDate", ""),
        "updated_at": "",
        "apply_url": CTRIP_BASE,
        "is_subsidiary": False,
        "description": text,
        "requirement": text,
        "company": COMPANY_NAME,
        "source": SOURCE,
        "raw": raw,
    }


def _strip_html(html: str) -> str:
    """HTML 转纯文本（保留段落结构）"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text("\n", strip=True)


async def fetch_detail(job: dict) -> dict:
    """携程岗位详情：从 description 切分职责/要求（官方来源，无网络请求）"""
    detail = _split_jd_text(job.get("description", ""), job.get("title", ""))
    detail["job_id"] = job["id"]
    detail["title"] = job["title"]
    detail["source"] = "official"
    return detail
