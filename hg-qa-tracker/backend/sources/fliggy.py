"""
飞猪 QA/测试相关岗位数据获取适配器
- 飞猪招聘站是 career.fliggy.com（单数）。careers.fliggy.com 是淘宝店铺，
  talent.alibaba.com 对该网络返回 403。
- 接口为 Spring 风格的双提交 cookie 防 CSRF：先 GET 列表页拿 XSRF-TOKEN cookie，
  再把它的值作为 _csrf 查询参数回传。纯 httpx 即可，无需 Playwright。
- 列表接口已随岗位返回 description(职责)/requirement(任职要求)，详情无需额外请求。
"""
import datetime as dt

import httpx

from .common import (
    _SSL_CONTEXT,
    _extract_list_items,
    _is_qa_title,
    infer_direction,
    infer_level,
)

# ── API 配置 ──────────────────────────────────────────────────
BASE = "https://career.fliggy.com"
LIST_PAGE = f"{BASE}/off-campus/position-list"
SEARCH_URL = f"{BASE}/position/search"
SOURCE = "fliggy"
COMPANY_NAME = "飞猪"
PAGE_SIZE = 100
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/126.0 Safari/537.36"
)


async def fetch_jobs() -> list[dict]:
    """获取飞猪 QA/测试相关社招岗位（全量拉取 + 本地标题过滤）"""
    all_raw: dict[int, dict] = {}

    async with httpx.AsyncClient(
        timeout=20.0,
        verify=_SSL_CONTEXT,
        headers={"User-Agent": UA, "Referer": LIST_PAGE},
        follow_redirects=True,
    ) as client:
        # 第一步：取 XSRF-TOKEN cookie（注意 cookie 名不是 _csrf）
        try:
            await client.get(LIST_PAGE)
        except Exception as e:
            print(f"[fliggy] 无法加载列表页: {e}")
            return []

        csrf = client.cookies.get("XSRF-TOKEN")
        if not csrf:
            print("[fliggy] 未能取得 XSRF-TOKEN cookie")
            return []

        headers = {
            "Content-Type": "application/json",
            "Origin": BASE,
            "Referer": LIST_PAGE,
            "X-XSRF-TOKEN": csrf,
        }

        # 第二步：分页拉全量。飞猪在招总量仅百余个，全量拉取再本地过滤比
        # 逐个关键词请求更省，也不会漏掉服务端关键词索引没覆盖、但我们的
        # 标题过滤能命中的岗位。（携程/小红书保留关键词循环是因为岗位池大得多。）
        page_index = 1
        while True:
            try:
                resp = await client.post(
                    f"{SEARCH_URL}?_csrf={csrf}",
                    json=_build_body(page_index),
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"[fliggy] API error page={page_index}: {e}")
                break

            if not data.get("success"):
                print(f"[fliggy] API error: {data.get('errorMsg')}")
                break

            content = data.get("content") or {}
            items = content.get("datas") or []
            if not items:
                break

            for item in items:
                jid = item.get("id")
                if jid is not None:
                    all_raw[jid] = item

            total = int(content.get("totalCount") or 0)
            if page_index * PAGE_SIZE >= total or len(all_raw) >= total:
                break
            page_index += 1

    # 按标题做 QA 过滤
    jobs = []
    for item in all_raw.values():
        title = item.get("name", "")
        if not _is_qa_title(title):
            continue
        jobs.append(_normalize(item))

    jobs.sort(key=lambda j: j.get("opened_at", ""), reverse=True)
    return jobs


def _build_body(page_index: int) -> dict:
    """构造 position/search 请求体（已验证：channel=group_official_site）"""
    return {
        "channel": "group_official_site",
        "language": "zh",
        "batchId": "",
        "categories": "",
        "deptCodes": [],
        "key": "",
        "pageIndex": page_index,
        "pageSize": PAGE_SIZE,
        "regions": "",
        "subCategories": "",
        "shareType": "",
        "shareId": "",
        "myReferralShareCode": "",
    }


def _ms_to_date(ms) -> str:
    """毫秒 epoch -> YYYY-MM-DD（前端 formatDate 只切分字符串，必须在此转换）"""
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def _normalize(raw: dict) -> dict:
    """标准化飞猪岗位数据"""
    title = raw.get("name", "")
    locations = raw.get("workLocations") or []
    city = "、".join(locations) if isinstance(locations, list) else str(locations)

    return {
        "id": f"{SOURCE}:{raw.get('id', '')}",
        "mj_code": raw.get("code") or "",
        "title": title,
        "commitment": "全职",
        "project": raw.get("project") or "通用/未指定",
        "direction": infer_direction(title),
        "level": infer_level(title),
        "category": raw.get("categoryName") or "飞猪社招",
        "department_id": None,
        "location": {
            "country": "中国",
            "city": city,
            "address": city,
        },
        "opened_at": _ms_to_date(raw.get("publishTime")),
        "updated_at": "",
        # 官方给的 positionUrl 带会话相关的 track_id，改用稳定的 positionId 形式
        "apply_url": f"{BASE}/off-campus/position-detail?positionId={raw.get('id', '')}",
        "is_subsidiary": False,
        "description": raw.get("description", ""),
        "requirement": raw.get("requirement", ""),
        "company": COMPANY_NAME,
        "source": SOURCE,
        "raw": raw,
    }


async def fetch_detail(job: dict) -> dict:
    """飞猪岗位详情：接口已分别给出职责与要求，直接按字段切分（官方来源，无网络请求）

    不能把两段拼起来交给 _split_jd_text：飞猪的文本里没有"岗位职责/任职要求"这类
    章节标题，共享解析器会退化成"按行对半砍"，把职责的最后几条错划进任职要求。
    这里章节边界是接口明确给出的，直接用。
    """
    # 任职要求里的"加分项"单列出来（无该段时 partition 返回原文 + 空串）
    requirement, _, bonus = job.get("requirement", "").partition("加分项")

    return {
        "job_id": job["id"],
        "title": job["title"],
        "responsibilities": _extract_list_items(job.get("description", ""))[:10],
        "requirements": _extract_list_items(requirement)[:15],
        "bonus": _extract_list_items(bonus)[:10],
        "source": "official",
    }
