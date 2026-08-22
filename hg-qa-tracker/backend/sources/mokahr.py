"""
鹰角网络 QA/测试开发岗位数据获取适配器
- 实时从 MokaHR API 获取岗位列表
- 从第三方网站爬取详细 JD（mianshima / haolietou），失败时按标题推断
"""
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .common import _SSL_CONTEXT, _is_qa_title, infer_direction, infer_level, _parse_jd_text

# ── MokaHR API 配置 ──────────────────────────────────────────
MOKA_BASE = "https://app.mokahr.com/api"
MOKA_JOBS_URL = f"{MOKA_BASE}/apply/jobs"
SITE_ID = "26325"
ORG_ID = "hypergryph"
ZHINENG_QA_ID = "113616"  # 质量管理类
SOURCE = "yingjiao"
COMPANY_NAME = "鹰角网络"

# 鹰角网络招聘官网
CAREER_BASE = "https://career.hypergryph.com"


async def fetch_jobs() -> list[dict]:
    """获取鹰角网络质量管理类所有在招岗位（已 QA 过滤 + 规范化）"""
    all_jobs = []
    page = 1

    async with httpx.AsyncClient(timeout=30.0, verify=_SSL_CONTEXT) as client:
        while True:
            params = {
                "siteId": SITE_ID,
                "orgId": ORG_ID,
                "zhinengId": ZHINENG_QA_ID,
                "page": page,
                "limit": 50,
            }
            try:
                resp = await client.get(MOKA_JOBS_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"[mokahr] API error page={page}: {e}")
                break

            jobs = data.get("jobs", [])
            if not jobs:
                break

            for job in jobs:
                if job.get("status") != "open":
                    continue
                normalized = _normalize_job(job)
                # 标题门槛（zhinengId 过滤为主，标题兜底）
                if _is_qa_title(normalized["title"]):
                    all_jobs.append(normalized)

            total = data.get("jobStats", {}).get("total", 0)
            if len(all_jobs) >= total:
                break
            page += 1

    # 按发布日期排序（最新在前）
    all_jobs.sort(key=lambda j: j.get("opened_at", ""), reverse=True)
    return all_jobs


def _normalize_job(raw: dict) -> dict:
    """标准化岗位数据"""
    loc = raw.get("location", {}) or raw.get("locations", [{}])[0] or {}

    # 从标题推断项目/方向/级别
    title = raw.get("title", "")
    project = _infer_project(title)
    direction = infer_direction(title)
    level = infer_level(title)

    return {
        "id": f"{SOURCE}:{raw.get('id', '')}",
        "mj_code": raw.get("mjCode", ""),
        "title": title,
        "commitment": raw.get("commitment", "全职"),
        "project": project,
        "direction": direction,
        "level": level,
        "category": raw.get("zhineng", {}).get("name", "质量管理类"),
        "department_id": raw.get("deptId"),
        "location": {
            "country": loc.get("country", "中国"),
            "city": "上海",
            "address": loc.get("address", ""),
        },
        "opened_at": raw.get("openedAt", ""),
        "updated_at": raw.get("updatedAt", ""),
        "apply_url": f"https://app.mokahr.com/apply/hypergryph/{SITE_ID}#/job/{raw.get('id', '')}/apply",
        "is_subsidiary": "生态子公司" in title,
        "description": raw.get("description", ""),
        "requirement": raw.get("requirement", ""),
        "company": COMPANY_NAME,
        "source": SOURCE,
        "raw": raw,
    }


def _infer_project(title: str) -> str:
    """从标题推断所属项目（鹰角专属）"""
    if "终末地" in title:
        return "明日方舟：终末地"
    if "明日方舟" in title:
        return "明日方舟"
    if "森空岛" in title:
        return "森空岛"
    if "UE" in title or "ue" in title.lower():
        return "UE项目（通用）"
    return "通用/未指定"


# ── JD 详情 ──────────────────────────────────────────────────
async def fetch_detail(job: dict) -> dict:
    """获取鹰角岗位详细 JD（爬取第三方来源，失败则按标题推断）"""
    job_id = job["id"]
    title = job["title"]

    detail = {
        "job_id": job_id,
        "title": title,
        "responsibilities": [],
        "requirements": [],
        "bonus": [],
        "source": "inferred",
    }

    # 尝试从第三方网站爬取
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=_SSL_CONTEXT) as client:
            d = await _scrape_mianshima(client, title)
            if d and d.get("responsibilities"):
                detail = d
            else:
                d = await _scrape_haolietou(client, title)
                if d and d.get("responsibilities"):
                    detail = d
    except Exception:
        pass

    # 如果爬取失败，根据标题生成推断性 JD
    if not detail.get("responsibilities"):
        detail = _infer_jd_from_title(title, job_id)

    return detail


async def _scrape_mianshima(client: httpx.AsyncClient, title: str) -> Optional[dict]:
    """从面试吗网站爬取 JD"""
    search_url = f"https://www.mianshima.com/search?q=鹰角网络+{title[:20]}"
    try:
        resp = await client.get(search_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        # 查找第一个职位卡
        card = soup.select_one(".job-card, .job-item, [class*=job]")
        if not card:
            return None
        text = card.get_text("\n", strip=True)
        return _parse_jd_text(text, title)
    except Exception:
        return None


async def _scrape_haolietou(client: httpx.AsyncClient, title: str) -> Optional[dict]:
    """从好猎头网站爬取 JD"""
    try:
        resp = await client.get(
            "https://www.haolietou.com/search",
            params={"kw": f"鹰角网络 {title[:15]}"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text("\n", strip=True)
        return _parse_jd_text(text, title)
    except Exception:
        return None


def _infer_jd_from_title(title: str, job_id: str) -> dict:
    """根据岗位标题推断 JD 内容"""
    is_senior = any(w in title for w in ["资深", "高级", "组长"])
    is_test_dev = any(w in title for w in ["测试开发", "测开"])
    is_qa = "QA" in title or "质检" in title
    direction = infer_direction(title)
    project = _infer_project(title)
    is_ue = "UE" in title or project == "UE项目（通用）"

    # 通用游戏测试职责
    base_resp = [
        "根据项目需求设计测试方案、编写测试用例并执行测试",
        "对游戏功能、系统进行全面的功能测试、集成测试和回归测试",
        "提交、跟踪和管理缺陷，推动问题的及时修复与闭环",
        "编写测试报告，对产品质量进行评估和风险预警",
        "与策划、开发、美术等团队紧密协作，保障版本交付质量",
    ]

    # 专项方向职责
    direction_resp = {
        "构建向": ["负责游戏构建系统的测试，包括资源打包、版本构建流程验证", "优化 CI/CD 流水线中的测试环节，提升构建效率与质量"],
        "系统向": ["负责游戏核心系统模块的测试（如任务、背包、社交、经济等）", "对系统间的耦合关系进行测试设计，保证系统交互正确性"],
        "战斗向": ["负责战斗系统、技能机制、数值平衡等核心玩法的测试", "设计战斗场景的自动化测试方案"],
        "关卡向": ["负责关卡内容的测试，包括关卡流程、碰撞、导航网格等", "验证关卡编辑器工具的功能正确性"],
        "场景向": ["负责游戏场景资源的测试，包括场景加载、LOD、碰撞检测", "对场景美术资源的质量进行把控"],
        "性能向": ["负责游戏性能测试，包括帧率、内存、CPU/GPU占用分析", "使用性能分析工具（如 PerfDog、UE Insights）定位性能瓶颈"],
        "引擎向": ["负责游戏引擎相关功能的测试，包括渲染、物理、动画等模块", "开发引擎测试工具，提升引擎模块的测试效率"],
        "工具向": ["负责游戏开发工具和编辑器的测试", "设计与开发自动化测试工具和测试框架"],
        "专项向": ["负责特定专项测试，如兼容性测试、网络测试、安全测试等"],
        "公共组": ["负责公共组件和服务的测试，为各项目组提供测试支持"],
        "海外质检": ["负责海外版本的语言质量、本地化内容审核", "协调海外测试团队，保障多语言版本质量"],
    }

    # 测试开发额外职责
    testdev_extra = [
        "开发和维护自动化测试框架与测试工具",
        "编写测试脚本，提升测试效率和覆盖率",
        "参与 CI/CD 流水线的搭建和优化",
    ]

    resp = base_resp.copy()
    if direction in direction_resp:
        resp = direction_resp[direction] + resp
    if is_test_dev:
        resp = testdev_extra + resp

    # 任职要求
    base_req = [
        "本科及以上学历，计算机、软件工程或相关专业",
    ]

    if is_senior:
        base_req.append("3-5年以上游戏测试或测试开发经验")
    else:
        base_req.append("1-3年游戏测试或测试开发经验")

    if is_ue:
        base_req.extend([
            "熟悉 Unreal Engine 引擎，了解 UE 的渲染、物理、动画等子系统",
            "熟练使用 UE 编辑器及相关调试工具",
        ])
    else:
        base_req.append("熟悉 Unity 或 Unreal Engine 游戏引擎")

    if is_test_dev:
        base_req.extend([
            "精通至少一种编程语言（Python/C++/Go/Java），有实际开发经验",
            "熟悉自动化测试框架（如 Selenium、Appium、AirTest 等）",
            "了解性能测试工具（如 PerfDog、UE Insights、RenderDoc）",
        ])
    else:
        base_req.extend([
            "熟悉至少一种编程或脚本语言（Python/Lua/C#）",
            "了解测试方法论，熟悉黑盒、白盒测试方法",
        ])

    base_req.extend([
        "熟悉游戏开发流程，了解敏捷开发模式",
        "具备良好的沟通能力和团队协作精神",
        "逻辑思维清晰，有较强的分析和问题定位能力",
    ])

    # 加分项
    bonus = []
    if "终末地" in project:
        bonus.append("有大型 RPG 或开放世界项目测试经验")
    if is_ue:
        bonus.append("有 UE4/UE5 项目实际开发或测试经验")
    if is_test_dev:
        bonus.append("有测试框架或工具从 0 到 1 的开发经验")
        bonus.append("熟悉 Docker/K8s 等容器化技术")
    bonus.extend([
        "热爱游戏，是明日方舟或其他鹰角游戏的核心玩家",
        "有二次元/ACG 文化背景，对美术品质有追求",
    ])

    return {
        "job_id": job_id,
        "title": title,
        "responsibilities": resp,
        "requirements": base_req,
        "bonus": bonus,
        "source": "inferred",
    }
