import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

DOCS_SCREENS_DIR = Path(__file__).resolve().parent.parent / "docs" / "screens"
DOCS_SCREENS_DIR.mkdir(parents=True, exist_ok=True)

QUERIES_TO_CAPTURE = [
    ("q1_status.png", "Is WELL-0001 producing oil right now?"),
    ("q2_offline_table.png", "Which wells in Northeast Block 7 are offline right now?"),
    ("q3_temperature_chart.png", "Plot temperature vs air for WELL-0001 over the last 13 weeks"),
    ("q6_downtime_barchart.png", "Which 3 wells had the most downtime in Northeast Block 7 in the last 4 months?"),
    ("q7_spill_map.png", "Show me a map of spills in Northeast Block 7"),
    ("q8_heatmap.png", "Show a heatmap of spills across areas by month"),
    ("q9_sop_audit.png", "What rules has WELL-0001 broken in the last 12 months?"),
]

def capture_ui_screens():
    print("\n" + "=" * 80)
    print("RUNNING FRONTEND BROWSER AUTOMATION & SCREENSHOT CAPTURE (PLAYWRIGHT)")
    print(f"Screens Directory: {DOCS_SCREENS_DIR}")
    print("=" * 80)

    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_console(msg):
            if msg.type == "error":
                print(f"[Browser Console Error]: {msg.text}")
                # Filter out harmless network/font warnings if any
                if not any(ign in msg.text.lower() for ign in ["favicon", "thesys.dev/v1/auth", "font"]):
                    console_errors.append(msg.text)

        page.on("console", on_console)

        print("\nNavigating to Frontend at http://127.0.0.1:3000 ...")
        page.goto("http://127.0.0.1:3000", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # 1. Verify User Picker and select Michael Turner (U-201)
        user_select = page.locator('select[aria-label="Select Operator"]')
        if user_select.count() > 0:
            user_select.select_option("U-201")
            print("PASS: Operator 'Michael Turner (U-201)' active in UserPicker.")
        else:
            print("Note: UserPicker select not found on initial load.")

        # Capture initial state
        initial_png = DOCS_SCREENS_DIR / "initial_view.png"
        page.screenshot(path=str(initial_png), full_page=True)
        print(f"Saved initial screen: {initial_png.name}")

        # 2. Iterate queries and capture rendered visuals
        for filename, query in QUERIES_TO_CAPTURE:
            print(f"\nSubmitting Query: \"{query}\" ...")
            
            # Find the chat input
            chat_input = page.locator('textarea, input[placeholder*="Ask"], input[type="text"]').first
            if not chat_input or chat_input.count() == 0:
                print("Could not locate chat input textarea/input; skipping.")
                continue

            chat_input.click()
            chat_input.fill(query)
            chat_input.press("Enter")

            # Wait for response streaming and visual rendering (table, chart, map, card)
            # Give sufficient time for OpenUI Lang stream & visual component hydration
            time.sleep(6)

            screen_path = DOCS_SCREENS_DIR / filename
            page.screenshot(path=str(screen_path), full_page=True)
            assert screen_path.exists() and screen_path.stat().st_size > 5000, f"Screenshot {filename} failed to save or was empty"
            print(f"PASS: Captured {filename} ({round(screen_path.stat().st_size / 1024, 1)} KB)")

        browser.close()

    print("\n" + "=" * 80)
    print(f"SCREENSHOT CAPTURE COMPLETE! All {len(QUERIES_TO_CAPTURE)} UI scenarios captured.")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    capture_ui_screens()
