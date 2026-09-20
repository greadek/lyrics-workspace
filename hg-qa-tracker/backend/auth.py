"""
登录鉴权 —— 零新依赖实现（仅用标准库）

设计取舍：
- 口令直接常数时间比较，不做 pbkdf2。这里没有"持久化的哈希"要保护：秘密来源是
  环境变量/常量，进程内从明文派生再配一个每次重启就换的随机盐，功能上等价于直接
  比较，只多出约 145ms 的 CPU 开销，而且会阻塞事件循环（未鉴权端点 = 廉价 DoS）。
  将来若真的引入凭据文件，再换成 pbkdf2 + 持久化盐。
- session 存在进程内存里，重启即失效。对本地单用户工具足够，且服务端 pop 掉 token
  就是真正的失效手段（这正是内存 session 优于"签名 cookie"的地方）。
- 固定 12 小时 TTL，不做滑动续期：滑动服务端 expires_at 但 cookie max_age 不刷新
  会自相矛盾，过期条目还会白占内存。
"""
import hmac
import os
import secrets
import time
from datetime import timedelta

# ── 配置 ──────────────────────────────────────────────────────
SESSION_COOKIE = "hg_session"
SESSION_TTL = timedelta(hours=12)

ADMIN_USER = os.environ.get("HG_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("HG_ADMIN_PASSWORD", "111111")
USING_DEFAULT_PASSWORD = ADMIN_PASS == "111111"

# 登录失败节流
MAX_FAILS = 5
LOCKOUT_SEC = 30.0

# ── 状态 ──────────────────────────────────────────────────────
_sessions: dict[str, dict] = {}  # token -> {"username": str, "expires_at": float}
_fails: dict[str, list] = {}  # ip -> [count, locked_until]


# ── 凭据校验 ──────────────────────────────────────────────────
def check_credentials(user: str, password: str) -> bool:
    """常数时间比较用户名与口令。

    注意：hmac.compare_digest 对**非 ASCII 的 str** 会抛
    TypeError("comparing strings with non-ASCII characters is not supported")，
    中文环境下必须比较 bytes。
    用 & 而非 and：两个比较都执行，不因用户名先错就跳过口令比较。
    """
    return hmac.compare_digest(
        user.encode("utf-8"), ADMIN_USER.encode("utf-8")
    ) & hmac.compare_digest(password.encode("utf-8"), ADMIN_PASS.encode("utf-8"))


# ── session ──────────────────────────────────────────────────
def new_session(username: str) -> str:
    """签发新 session token"""
    _prune()
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "expires_at": time.time() + SESSION_TTL.total_seconds(),
    }
    return token


def get_session(token: str | None) -> dict | None:
    """取 session，过期即惰性删除并返回 None"""
    if not token:
        return None
    sess = _sessions.get(token)
    if sess is None:
        return None
    if sess["expires_at"] < time.time():
        _sessions.pop(token, None)
        return None
    return sess


def drop_session(token: str | None) -> None:
    """销毁 session（登出）"""
    _sessions.pop(token or "", None)


def _prune() -> None:
    """清掉过期 session 与已解锁的失败计数（避免字典无界增长）"""
    now = time.time()
    for t in [t for t, s in _sessions.items() if s["expires_at"] < now]:
        _sessions.pop(t, None)
    for ip in [
        ip
        for ip, rec in _fails.items()
        if rec[0] >= MAX_FAILS and rec[1] and rec[1] < now
    ]:
        _fails.pop(ip, None)


# ── 失败节流 ──────────────────────────────────────────────────
def client_ip(request) -> str:
    """request.client 在非 TCP 传输下可能为 None"""
    return request.client.host if request.client else "unknown"


def is_locked(ip: str) -> bool:
    rec = _fails.get(ip)
    return bool(rec and rec[1] and rec[1] > time.time())


def note_failure(ip: str) -> None:
    """记一次失败；达到阈值后锁定"""
    count = _fails.get(ip, [0, 0.0])[0] + 1
    _fails[ip] = [count, time.time() + LOCKOUT_SEC if count >= MAX_FAILS else 0.0]


def clear_failures(ip: str) -> None:
    """登录成功即清零"""
    _fails.pop(ip, None)
