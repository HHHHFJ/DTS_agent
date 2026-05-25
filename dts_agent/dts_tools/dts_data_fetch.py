#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DTS 系统自动化导出脚本 - 使用 persistent 上下文自动登录
功能：
1. 使用 persistent 上下文自动登录
2. 勾选目标版本（BeiMing-I 26, BeiMing 25）
3. 筛选提出方（验证管理部）
4. 自动遍历所有分页
5. 导出 Excel，包含修改文件清单列
"""

import time
import re
import os
import argparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from openpyxl import Workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

# 配置
DTS_URL = "https://dts.huawei.com/DTSPortal/workspace/versions"
TARGET_VERSIONS = ["BeiMing-I 26", "BeiMing 25"]
FILTER_DEPARTMENT = "验证管理部"
OUTPUT_DIR = r"D:\test"
OUTPUT_FILENAME = "DTS 问题单汇总.xlsx"


def parse_args():
    """Parse optional output path arguments without changing existing defaults."""
    parser = argparse.ArgumentParser(description="Fetch DTS tickets and export an Excel file.")
    parser.add_argument("--output-dir", help="Directory where the generated Excel should be saved.")
    parser.add_argument("--output-file", help="Exact generated Excel file path.")
    args, _unknown = parser.parse_known_args()
    return args


def resolve_output_path(args=None) -> str:
    """Resolve DTS Excel output path from environment, then fallback defaults."""
    output_file = (
        getattr(args, "output_file", None)
        or os.environ.get("DTS_EXCEL_OUTPUT_FILE")
        or os.environ.get("DTS_FETCH_OUTPUT_FILE")
    )
    if output_file:
        output_path = os.path.abspath(output_file)
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        return output_path

    output_dir = (
        getattr(args, "output_dir", None)
        or os.environ.get("DTS_EXCEL_OUTPUT_DIR")
        or os.environ.get("DTS_FETCH_OUTPUT_DIR")
        or OUTPUT_DIR
    )
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, OUTPUT_FILENAME)


# Excel 列定义
COLUMNS = [
    "序号",
    "问题单号",
    "简要描述",
    "严重程度",
    "创建时间",
    "提出方",
    "修改文件清单"
]

# 严重程度着色配置
SEVERITY_FILLS = {
    "致命": PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid"),
    "严重": PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid"),
    "提示": PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid"),
    "一般": PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid"),
}


def wait_seconds(seconds: int, description: str = ""):
    """等待指定秒数"""
    if description:
        print(f"  [等待] {description}... {seconds}秒")
    time.sleep(seconds)


def extract_modification_files(text: str) -> list:
    """从文本中提取修改文件清单"""
    files = []
    pattern = r'https://[^\s]+/(?:merge_requests|pull)/\d+'
    urls = re.findall(pattern, text)
    for url in urls:
        files.append(url)
    return files


def parse_row_data(cells) -> dict:
    """解析一行数据"""
    data = {
        "问题单号": "",
        "简要描述": "",
        "严重程度": "",
        "创建时间": "",
        "提出方": "",
        "修改文件清单": "",
        "原始文本": ""
    }

    if not cells or len(cells) == 0:
        return data

    all_text = ""
    cell_texts = []

    for i, cell in enumerate(cells):
        try:
            if hasattr(cell, 'inner_text'):
                text = cell.inner_text().strip()
            elif hasattr(cell, 'evaluate'):
                text = cell.evaluate("el => el.innerText").strip()
            else:
                continue

            cell_texts.append((i, text))
            all_text += text + " | "
        except Exception:
            continue

    data["重复单号"] = cell_texts[6][1]
    data["问题单号"] = cell_texts[2][1]
    data["严重程度"] = cell_texts[4][1]
    data["创建时间"] = cell_texts[5][1]
    data["提出方"] = cell_texts[10][1]
    data["简要描述"] = cell_texts[3][1]
    data["修改文件清单"] = str(extract_modification_files(cell_texts[7][1]))

    return data


def create_excel(data_list: list, output_path: str):
    """创建 Excel 文件"""
    print(f"\n[生成 Excel] 正在生成文件：{output_path}")

    wb = Workbook()
    ws = wb.active
    ws.title = "问题单汇总"

    # 写入表头
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    for col_idx, col_name in enumerate(COLUMNS, 1):
        ws.cell(row=1, column=col_idx, value=col_name)
        ws.cell(row=1, column=col_idx).fill = header_fill

    # 写入数据
    for row_idx, data in enumerate(data_list, 2):
        ws.cell(row=row_idx, column=1, value=row_idx - 1)
        ws.cell(row=row_idx, column=2, value=data.get("问题单号", ""))
        ws.cell(row=row_idx, column=3, value=data.get("简要描述", ""))

        severity = data.get("严重程度", "")
        ws.cell(row=row_idx, column=4, value=severity)
        if severity in SEVERITY_FILLS:
            ws.cell(row=row_idx, column=4).fill = SEVERITY_FILLS[severity]

        ws.cell(row=row_idx, column=5, value=data.get("创建时间", ""))
        ws.cell(row=row_idx, column=6, value=data.get("提出方", ""))
        ws.cell(row=row_idx, column=7, value=data.get("修改文件清单", ""))

    # 调整列宽
    column_widths = {1: 8, 2: 20, 3: 50, 4: 10, 5: 15, 6: 15, 7: 60}
    for col_idx, width in column_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    wb.save(output_path)
    print(f"  [成功] Excel 文件已生成，共 {len(data_list)} 条记录")


def main():
    """主函数"""
    args = parse_args()
    print("=" * 60)
    print("DTS 系统问题单自动导出脚本 (Persistent 模式)")
    print("=" * 60)

    # 获取用户数据目录
    user_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "DTS-Persistent-Profile")

    with sync_playwright() as p:
        # 启动 persistent 上下文（自动登录）
        print("\n[启动] 正在启动浏览器 (Persistent 模式)...")
        print(f"  [信息] 用户数据目录：{user_data_dir}")

        # 查找本地 Chrome 浏览器路径
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        ]

        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break

        if not chrome_path:
            print("\n[错误] 未找到 Chrome 浏览器")
            return

        print(f"  [使用] Chrome 路径：{chrome_path}")

        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            executable_path=chrome_path,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        page = context.new_page()

        try:
            # 访问 DTS 系统
            print(f"\n[访问] 正在访问 DTS 系统：{DTS_URL}")
            page.goto(DTS_URL, wait_until="networkidle", timeout=60000)

            # 等待自动登录
            print("\n[等待] 等待自动登录... 5 秒")
            wait_seconds(5, "自动登录")

            # 步骤 1: 展开所有版本并勾选目标版本
            print(f"\n[步骤 1] 正在勾选目标版本：{', '.join(TARGET_VERSIONS)}")

            versions_checked = 0

            # 1.1 展开所有版本
            print("  [操作] 正在展开所有版本...")
            try:
                all_versions = page.locator('text=所有版本').first
                if all_versions.is_visible():
                    all_versions.click()
                    print("  [成功] 已点击展开所有版本")
                    wait_seconds(2, "版本展开")
            except Exception as e:
                print(f"  [警告] 展开版本失败：{str(e)}")

            # 1.2 搜索并勾选目标版本
            for version in TARGET_VERSIONS:
                print(f"\n  [处理] 正在搜索版本：{version}")

                try:
                    version_search = page.locator('input[placeholder*="仅支持按名称进行左匹配搜索"]').first

                    if version_search.count() > 0 and version_search.is_visible():
                        version_search.fill("")
                        version_search.fill(version)
                        version_search.press("Enter")
                        print(f"    [输入] 已输入 {version} 并回车")
                        wait_seconds(3, "搜索生效")

                        version_item = page.locator(f'text={version}').first

                        if version_item.count() > 0 and version_item.is_visible():
                            print(f"    [找到] 版本：{version}")
                            version_item.click()
                            print(f"    [成功] 已勾选 {version}")
                            versions_checked += 1
                            wait_seconds(1, "勾选生效")
                        else:
                            print(f"    [警告] 未找到版本：{version}")
                    else:
                        print(f"    [警告] 未找到版本搜索框")

                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass

                except Exception as e:
                    print(f"    [错误] 勾选版本 {version} 失败：{str(e)}")

                if "workspace/versions" not in page.url:
                    print("  [返回] 正在返回版本列表...")
                    page.go_back()
                    wait_seconds(2, "页面返回")

            if versions_checked == 0:
                print("\n[错误] 步骤 1 执行失败，无法勾选任何目标版本")
                context.close()
                return

            print(f"  [成功] 步骤 1 完成，已勾选 {versions_checked}/{len(TARGET_VERSIONS)} 个版本")

            # 步骤 2: 过滤提出部门
            print(f"\n[步骤 2] 正在过滤提出部门：{FILTER_DEPARTMENT}")

            step2_success = False
            try:
                label = page.locator('span[title="提出方"]').first

                if label.count() > 0 and label.is_visible():
                    print("  [找到] 提出方标签")

                    dropdown = label.locator(
                        'xpath=following-sibling::*[contains(@class, "dropdown") or contains(@class, "select") or @role="combobox"]'
                    ).first

                    if not dropdown.count() > 0 or not dropdown.is_visible():
                        parent = label.locator('xpath=ancestor::*[self::td or self::div][1]').first
                        dropdown = parent.locator(
                            '[class*="dropdown"], [class*="select"], [role="combobox"], input').first

                    if dropdown.count() > 0 and dropdown.is_visible():
                        print("  [找到] 下拉框")

                        dropdown.scroll_into_view_if_needed()
                        wait_seconds(0.5)
                        dropdown.click()
                        print("  [点击] 已点击下拉框")
                        wait_seconds(1.5)

                        target_label = page.locator(f'label[title="{FILTER_DEPARTMENT}"]').first

                        if target_label.count() > 0 and target_label.is_visible():
                            target_label.click()
                            print(f"  [点击] 已点击 '{FILTER_DEPARTMENT}' 选项")
                            wait_seconds(0.5)

                            confirm_btn_span = page.locator('span.button-content:has-text("确定")').first

                            if confirm_btn_span.count() > 0:
                                confirm_btn = confirm_btn_span.locator('xpath=..').first
                                confirm_btn.click()
                                print("  [点击] 已点击'确定'按钮")
                                wait_seconds(1)

                                print("  [等待] 等待数据过滤...")
                                try:
                                    page.wait_for_load_state("networkidle", timeout=10000)
                                except PlaywrightTimeoutError:
                                    pass
                                wait_seconds(1)
                                print("  [成功] 数据过滤完成")
                                step2_success = True
                            else:
                                print("  [错误] 未找到'确定'按钮")
                        else:
                            print(f"  [错误] 未找到 '{FILTER_DEPARTMENT}' 选项")
                    else:
                        print("  [错误] 未找到下拉框")
                else:
                    print("  [错误] 未找到提出方标签")

            except Exception as e:
                print(f"  [错误] 选择提出方失败：{str(e)}")
                import traceback
                traceback.print_exc()

            if not step2_success:
                print("\n[错误] 步骤 2 执行失败，无法筛选提出方")
                context.close()
                return

            # 步骤 3: 遍历所有分页，提取数据
            print("\n[步骤 3] 正在提取数据...")

            data_list = []
            current_page = 1
            total_pages = 1

            while True:
                print(f"\n  [处理] 正在处理第 {current_page} 页...")

                try:
                    target_table = page.locator('table.devui-table')
                    all_tr = target_table.locator("tr").count()

                    virtual_scroll = None
                    if all_tr < 20:
                        # 查找虚拟滚动容器
                        virtual_scroll = target_table.locator('xpath=ancestor::cdk-virtual-scroll-viewport[1]').first

                        if virtual_scroll.count() > 0:
                            print(f"    [发现] 检测到虚拟滚动容器 (cdk-virtual-scroll-viewport)")
                            # print(f"    [策略] 将在提取数据时滚动以加载所有行")
                        else:
                            print(f"    [信息] 未检测到虚拟滚动容器")
                    rows = target_table.locator("tr").all()

                    if not rows or len(rows) == 0:
                        print("    [警告] 当前页无数据")
                        break

                    page_data = []
                    skipped_rows = 0
                    extracted_issue_numbers = set()  # 记录已提取的问题单号，避免重复

                    # 如果有虚拟滚动，需要滚动提取
                    if virtual_scroll and virtual_scroll.count() > 0:
                        print(f"    [策略] 使用滚动提取模式...")

                        # 滚动提取多轮
                        max_scroll_times = 5  # 最多滚动 5 次
                        last_count = 0

                        for scroll_idx in range(max_scroll_times):
                            # 滚动到不同位置
                            scroll_offset = scroll_idx * 200  # 每次滚动 200px
                            virtual_scroll.evaluate(f"el => el.scrollTop = {scroll_offset}")
                            wait_seconds(0.5, f"第{scroll_idx + 1}次滚动")

                            # 获取当前可见行
                            current_rows = target_table.locator("tbody tr").all()
                            if len(current_rows) == 0:
                                current_rows = target_table.locator("tr").all()

                            print(f"    [滚动{scroll_idx + 1}] 当前可见 {len(current_rows)} 行，偏移 {scroll_offset}px")

                            # 提取当前可见行
                            for row in current_rows:
                                try:
                                    cells = row.locator("td").all()
                                    if cells and len(cells) > 0:
                                        row_data = parse_row_data(cells)
                                        issue_no = row_data.get("问题单号")

                                        # 避免重复提取
                                        if issue_no and issue_no not in extracted_issue_numbers:
                                            extracted_issue_numbers.add(issue_no)
                                            page_data.append(row_data)
                                        elif not issue_no:
                                            skipped_rows += 1

                                except Exception as e:
                                    skipped_rows += 1
                                    continue

                            # 如果本轮没有新数据，停止滚动
                            current_total = len(page_data)
                            if current_total == last_count or current_total == 20:
                                print(f"    [完成] 未提取到新数据，停止滚动")
                                break
                            last_count = current_total

                        # 滚回顶部
                        virtual_scroll.evaluate("el => el.scrollTop = 0")
                        wait_seconds(0.5)

                    data_list.extend(page_data)

                    if not page_data:
                        print("    [提示] 当前页无有效数据，停止遍历")
                        break

                    # 获取总页数（只在第 1 页时计算）
                    if current_page == 1:
                        try:
                            # 尝试多种方式获取分页信息
                            pagination_text = ""

                            # 方式 1: 查找分页信息容器
                            pagination_container = page.locator(
                                '.devui-pagination, [class*="pagination"], .el-pagination').first
                            if pagination_container.count() > 0:
                                pagination_text = pagination_container.inner_text()

                            if pagination_text:
                                # 清理文本（移除换行符）
                                pagination_clean = re.sub(r'\s+', ' ', pagination_text)

                                # 提取所有数字（最可靠的方法）
                                all_numbers = re.findall(r'\d+', pagination_clean)

                                if len(all_numbers) >= 2:
                                    # 第一个数字是每页条数，第二个是总记录数
                                    records_per_page = int(all_numbers[0])
                                    total_records = int(all_numbers[1])
                                    total_pages = (total_records + records_per_page - 1) // records_per_page
                                    print(
                                        f"    [计算] 每页：{records_per_page}条，总记录：{total_records}条，总页数：{total_pages}")
                        except Exception as e:
                            print(f"    [错误] 获取分页信息失败：{str(e)}")

                    # 判断是否还有下一页
                    if current_page >= total_pages:
                        print(f"\n  [完成] 已处理所有 {total_pages} 页")
                        break

                    # 使用"跳至"输入框直接跳转到指定页
                    print(f"  [翻页] 正在跳转到第 {current_page + 1} 页...")

                    try:
                        current_page = current_page + 1

                        # 定位"跳至"输入框
                        jump_input = page.locator('.devui-jump-container input[type="text"][name="pageIndex"]').first

                        if jump_input.count() > 0 and jump_input.is_visible():
                            # 清空并输入目标页数
                            jump_input.fill("")
                            jump_input.fill(str(current_page))

                            # 按回车确认
                            jump_input.press("Enter")

                            # 等待页面加载
                            wait_seconds(3, "页面跳转")

                    except Exception as e:
                        print(f"  [完成] 翻页失败：{str(e)}")
                        break

                except Exception as e:
                    print(f"  [错误] 处理第 {current_page} 页失败：{str(e)}")
                    break

            # 步骤 4: 生成 Excel
            if data_list:
                output_path = resolve_output_path(args)
                create_excel(data_list, output_path)
                print(f"\n[完成] 任务执行成功！")
                print(f"  文件位置：{output_path}")
            else:
                print("\n[错误] 未提取到任何数据")

        except Exception as e:
            print(f"\n[错误] 执行过程中发生错误：{str(e)}")
            import traceback
            traceback.print_exc()

        finally:
            print("\n[关闭] 正在关闭浏览器...")
            context.close()
            print("[完成] 脚本执行结束")


if __name__ == "__main__":
    main()
