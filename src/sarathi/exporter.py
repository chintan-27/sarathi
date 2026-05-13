from __future__ import annotations

from pathlib import Path


def to_pdf(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(f"file://{html_path.resolve()}", wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.pdf(
            path=str(pdf_path),
            width="1280px",
            height="720px",
            print_background=True,
        )
        browser.close()
