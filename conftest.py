"""
pytest 配置与自定义 fixture

pytest-playwright 插件内置的 fixture：
  - page      ：每个测试独立的页面对象
  - browser   ：浏览器实例
  - context   ：浏览器上下文（可用于登录态隔离）
"""

import pytest
from playwright.sync_api import Browser, Page


@pytest.fixture(scope="session")
def base_url() -> str:
    """全局基础 URL，可通过环境变量覆盖"""
    return "https://playwright.dev/python/"


@pytest.fixture(scope="function")
def authenticated_page(browser: Browser, base_url: str) -> Page:
    """
    演示自定义 fixture：
    创建带持久化状态的上下文（如登录态、localStorage），
    供需要登录的测试使用。
    """
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        # 通过 storage_state 可复用已保存的登录态
        # storage_state="auth_state.json",
    )
    page = context.new_page()
    page.goto(base_url)
    yield page
    context.close()


@pytest.fixture(scope="session")
def auth_storage_state(browser: Browser) -> str:
    """
    登录态保存示例：
    登录一次后把状态存为 JSON，其他测试直接复用，避免重复登录。
    """
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://playwright.dev/python/")
    # ... 此处执行真实登录操作 ...
    # 登录成功后保存状态
    state_file = "auth_state.json"
    context.storage_state(path=state_file)
    context.close()
    return state_file
