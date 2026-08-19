"""
pytest + Playwright 测试用例示例

依赖：pytest、playwright、pytest-playwright
运行：pytest test_example.py          # 无头模式
      pytest test_example.py --headed # 有头模式
      pytest test_example.py --browser chromium --browser firefox  # 多浏览器
"""

import re

import pytest
from playwright.sync_api import Page, expect


class TestHomePage:
    """首页基础测试"""

    def test_homepage_has_correct_title(self, page: Page) -> None:
        """验证页面标题"""
        page.goto("https://playwright.dev/python/")
        expect(page).to_have_title(re.compile("Playwright"))

    def test_navigation_link_exists(self, page: Page) -> None:
        """验证导航链接存在且可点击"""
        page.goto("https://playwright.dev/python/")
        docs_link = page.get_by_role("link", name="Docs")
        expect(docs_link).to_be_visible()
        expect(docs_link).to_be_enabled()

    def test_click_link_and_verify_url(self, page: Page) -> None:
        """点击链接后验证跳转"""
        page.goto("https://playwright.dev/python/")
        page.get_by_role("link", name="Docs").first.click()
        expect(page).to_have_url(re.compile("/docs/"))

    def test_search_functionality(self, page: Page) -> None:
        """演示表单交互：搜索并验证结果"""
        page.goto("https://playwright.dev/python/docs/intro")
        search_input = page.get_by_placeholder("Search docs")
        search_input.fill("fixtures")
        # 使用 playwright 的自动等待能力，验证出现结果链接
        result = page.get_by_role("link", name=re.compile("Using test fixtures"))
        expect(result).to_be_visible()


@pytest.mark.parametrize("keyword", ["fixtures", "emulation"])
def test_search_keywords(page: Page, keyword: str) -> None:
    """参数化测试：多个关键词批量验证搜索"""
    page.goto("https://playwright.dev/python/docs/intro")
    page.get_by_placeholder("Search docs").fill(keyword)
    expect(page.locator(".algolia-autocomplete, .DocSearch-Container").first).to_be_visible()


def test_take_screenshot(page: Page) -> None:
    """截图：测试结束后保存页面截图"""
    page.goto("https://playwright.dev/python/")
    page.screenshot(path="screenshots/homepage.png", full_page=True)
    # 断言截图文件已生成（简单验证）
    import os

    assert os.path.exists("screenshots/homepage.png")


def test_responsive_viewport(page: Page) -> None:
    """自定义视口：移动端分辨率下验证页面"""
    page.set_viewport_size({"width": 375, "height": 812})  # iPhone X 尺寸
    page.goto("https://playwright.dev/python/")
    # 移动端下导航栏可能折叠，验证汉堡菜单按钮存在
    menu_button = page.locator(".mobile-menu, [aria-label='Menu'], .navbar__toggle")
    expect(menu_button.first).to_be_visible()
