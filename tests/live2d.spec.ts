/**
 * AzurLane Live2D Viewer (https://l2d.su/cn/) 测试用例
 *
 * 运行方式：
 *   npx playwright test tests/live2d.spec.ts             # 仅本文件（按配置跑全部浏览器）
 *   npx playwright test tests/live2d.spec.ts --project=chromium   # 只跑 chromium，更快
 *   npx playwright test tests/live2d.spec.ts --headed    # 有头模式，能看到浏览器操作
 */

import { test, expect, Page } from '@playwright/test';

const BASE_URL = 'https://l2d.su/cn/';

/** 搜索框定位：placeholder 为「舰船名 / ID / 皮肤」 */
const searchBox = (page: Page) => page.getByPlaceholder('舰船名 / ID / 皮肤');

/** 打开页面并等待舰船列表加载完成（计数出现即视为就绪） */
async function gotoReady(page: Page) {
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await expect(page.getByText(/显示 \d+ \/ \d+/).first()).toBeVisible();
}

test.describe('首页基础', () => {
  test('页面标题正确', async ({ page }) => {
    await page.goto(BASE_URL);
    await expect(page).toHaveTitle(/Live2D Viewer/);
  });

  test('舰船总数显示 888', async ({ page }) => {
    await gotoReady(page);
    await expect(page.getByText('显示 888 / 888').first()).toBeVisible();
  });

  test('「近期更新」板块可见', async ({ page }) => {
    await gotoReady(page);
    await expect(page.getByRole('heading', { name: '近期更新' })).toBeVisible();
  });

  test('「跳到模型展示区」锚点链接', async ({ page }) => {
    await gotoReady(page);
    const jump = page.getByRole('link', { name: '跳到模型展示区' });
    await expect(jump).toHaveAttribute('href', '#main-content');
    // 跳过链接通常定位在视口外，Playwright 拒绝直接点击；
    // 用键盘操作触发，更贴近真实用户行为
    await jump.focus();
    await jump.press('Enter');
    await expect(page).toHaveURL(/#main-content/);
  });
});

test.describe('搜索', () => {
  test('按舰船名搜索并过滤列表', async ({ page }) => {
    await gotoReady(page);
    await searchBox(page).fill('拉菲');
    // 只匹配到「拉菲」与「拉菲II」两个结果
    await expect(page.getByText('显示 2 / 888').first()).toBeVisible();
    await expect(page.locator('button').filter({ hasText: '#10117' })).toBeVisible();
    await expect(page.locator('button').filter({ hasText: '#10151' })).toBeVisible();
  });

  test('按舰船 ID 搜索', async ({ page }) => {
    await gotoReady(page);
    await searchBox(page).fill('10117');
    await expect(page.getByText('显示 1 / 888').first()).toBeVisible();
    await expect(page.locator('button').filter({ hasText: '#10117' })).toBeVisible();
  });

  test('清除搜索后恢复完整列表', async ({ page }) => {
    await gotoReady(page);
    await searchBox(page).fill('拉菲');
    await expect(page.getByText('显示 2 / 888').first()).toBeVisible();
    await searchBox(page).clear();
    await expect(page.getByText('显示 888 / 888').first()).toBeVisible();
  });
});

test.describe('筛选', () => {
  test('点击「筛选」打开筛选面板', async ({ page }) => {
    await gotoReady(page);
    await page.getByRole('button', { name: '筛选' }).click();
    await expect(page.getByText('清空筛选')).toBeVisible();
    for (const label of ['阵营', '舰种', '动态能力', '皮肤系列']) {
      await expect(page.getByText(label).first()).toBeVisible();
    }
  });
});

test.describe('查看器交互', () => {
  test('点击舰船后显示其皮肤列表', async ({ page }) => {
    await gotoReady(page);
    await searchBox(page).fill('拉菲');
    await page.locator('button').filter({ hasText: '#10117' }).click();
    // 选中舰船后，查看器区域出现该舰船的默认 Live2D 皮肤入口
    // （按钮由多个 span 组成，accessible name 会带空格，用正则做子串匹配）
    await expect(page.getByRole('button', { name: /默认.*Live2D/ })).toBeVisible();
  });

  test('搜索无结果时列表为空', async ({ page }) => {
    await gotoReady(page);
    await searchBox(page).fill('不存在的舰船XYZ');
    await expect(page.getByText('显示 0 / 888').first()).toBeVisible();
  });
});
