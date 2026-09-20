"""
多公司数据源注册表
每个公司一个适配器模块，统一契约：
- async fetch_jobs() -> list[dict]    # 已 QA 过滤的规范化岗位
- fetch_detail(job) -> dict           # 生成 JD 详情（无缓存，由编排器缓存）
- liveness_url                        # 轻量可达性探测 URL
"""
from . import mokahr, ctrip, bilibili, xiaohongshu, fliggy

COMPANIES: dict[str, dict] = {
    "yingjiao": {
        "name": "鹰角网络",
        "fetch": mokahr.fetch_jobs,
        "detail": mokahr.fetch_detail,
        "liveness_url": (
            "https://app.mokahr.com/api/apply/jobs"
            "?siteId=26325&orgId=hypergryph&zhinengId=113616&page=1&limit=1"
        ),
    },
    "ctrip": {
        "name": "携程",
        "fetch": ctrip.fetch_jobs,
        "detail": ctrip.fetch_detail,
        "liveness_url": "https://careers.ctrip.com/",
    },
    "bilibili": {
        "name": "B站",
        "fetch": bilibili.fetch_jobs,
        "detail": bilibili.fetch_detail,
        "liveness_url": "https://jobs.bilibili.com/social",
    },
    "xiaohongshu": {
        "name": "小红书",
        "fetch": xiaohongshu.fetch_jobs,
        "detail": xiaohongshu.fetch_detail,
        "liveness_url": "https://job.xiaohongshu.com/",
    },
    "fliggy": {
        "name": "飞猪",
        "fetch": fliggy.fetch_jobs,
        "detail": fliggy.fetch_detail,
        "liveness_url": "https://career.fliggy.com/off-campus/position-list",
    },
}

# 各公司抓取超时（秒）。B站需启动无头浏览器，给更长时间。
FETCH_TIMEOUTS: dict[str, float] = {
    "yingjiao": 30.0,
    "ctrip": 30.0,
    "bilibili": 60.0,
    "xiaohongshu": 30.0,
    "fliggy": 30.0,
}
