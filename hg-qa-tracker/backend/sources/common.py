"""
多公司共享工具函数
- SSL 上下文（Windows 证书库）
- QA 标题关键词过滤
- 通用方向/级别推断
- JD 文本解析（职责/要求/加分项）
"""
import re
import ssl
from typing import Optional

# 使用 Windows 系统证书库而非 certifi：
# 此环境下 certifi 证书链验证失败（CERTIFICATE_VERIFY_FAILED），
# 而 Windows 系统证书库（与 urllib/浏览器一致）可正常验证。
_SSL_CONTEXT = ssl.create_default_context()

# ── QA 关键词过滤 ────────────────────────────────────────────
QA_KEYWORDS = ["测试", "QA", "质检", "质量", "测开", "tester"]


def _is_qa_title(title: str) -> bool:
    """标题是否为 QA/测试相关岗位（大小写不敏感）"""
    t = title.lower()
    return any(kw.lower() in t for kw in QA_KEYWORDS)


# ── 通用方向推断（去游戏硬编码）─────────────────────────────────
def infer_direction(title: str) -> str:
    """从标题推断测试方向（跨公司通用）"""
    mapping = {
        "构建": "构建向",
        "系统": "系统向",
        "战斗": "战斗向",
        "关卡": "关卡向",
        "场景": "场景向",
        "性能": "性能向",
        "引擎": "引擎向",
        "工具": "工具向",
        "专项": "专项向",
        "公共": "公共组",
        "海外": "海外质检",
        "支付": "支付",
        "数据": "数据/平台",
        "打包": "打包/构建",
        "云游戏": "云游戏",
        "包体": "包体管理",
        "自动化": "自动化测试",
        "接口": "接口测试",
        "APP": "APP测试",
        "App": "APP测试",
        "app": "APP测试",
        "Web": "Web测试",
        "web": "Web测试",
        "客户端": "客户端测试",
        "服务端": "服务端测试",
        "游戏": "游戏测试",
        "质检": "质检",
    }
    for key, val in mapping.items():
        if key in title:
            return val
    return "综合"


def infer_level(title: str) -> str:
    """从标题推断级别（跨公司通用）"""
    if "资深" in title or "高级" in title:
        return "资深/高级"
    if "组长" in title or "负责人" in title or "经理" in title or "Manager" in title:
        return "管理"
    return "初中级"


# ── JD 文本解析 ──────────────────────────────────────────────
def _extract_list_items(text: str) -> list[str]:
    """从文本中提取列表项"""
    items = []
    # 按序号分割
    lines = re.split(r'(?:\d+[\.\、\)）]|\n\s*[•\-–—·●◆▪▸►✓✅⭐])', text)
    for line in lines:
        line = line.strip()
        if len(line) > 5 and not line.startswith(("http", "www", "薪资", "地点")):
            items.append(line)
    if not items:
        # fallback: 按句号分
        items = [s.strip() + "。" for s in text.split("。") if len(s.strip()) > 5]
    return items[:15]


def _parse_jd_text(text: str, title: str = "") -> Optional[dict]:
    """从文本中解析 JD 结构"""
    result = {"responsibilities": [], "requirements": [], "bonus": [], "source": "scraped"}

    # 岗位职责
    resp_match = re.search(r'(?:岗位职责|工作职责|职位描述|工作内容)[：:\s]*(.+?)(?=任职要求|岗位要求|任职资格|加分项|我们希望你|$)', text, re.DOTALL)
    if resp_match:
        items = _extract_list_items(resp_match.group(1))
        result["responsibilities"] = items[:10]

    # 任职要求
    req_match = re.search(r'(?:任职要求|岗位要求|任职资格|职位要求)[：:\s]*(.+?)(?=加分项|优先条件|薪酬|工作地址|$)', text, re.DOTALL)
    if req_match:
        items = _extract_list_items(req_match.group(1))
        result["requirements"] = items[:15]

    # 加分项
    bonus_match = re.search(r'(?:加分项|优先条件|优先考虑)[：:\s]*(.+?)(?=薪酬|工作地址|$)', text, re.DOTALL)
    if bonus_match:
        items = _extract_list_items(bonus_match.group(1))
        result["bonus"] = items[:10]

    if result["responsibilities"] or result["requirements"]:
        return result
    return None


def _split_jd_text(text: str, title: str = "") -> dict:
    """从原始 JD 全文切分职责/要求（官方来源，无推断 fallback）"""
    parsed = _parse_jd_text(text, title)
    if parsed:
        return parsed

    # 无法按章节切分时，整体按行分段：奇数段算职责，偶数段算要求
    lines = [l.strip() for l in re.split(r'\n+', text) if len(l.strip()) > 6]
    responsibilities = lines[: max(1, len(lines) // 2)]
    requirements = lines[len(responsibilities):]
    return {
        "responsibilities": responsibilities[:10],
        "requirements": requirements[:10],
        "bonus": [],
        "source": "official",
    }
