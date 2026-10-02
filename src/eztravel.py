import os
import re
import sys
import json
import subprocess
from datetime import datetime

from playwright.sync_api import sync_playwright, Error as PlaywrightError

# config.py 只當作預設值，實際以 run_pipeline.py 傳進來的環境變數為主
try:
    from config import ORIGIN, DESTINATION, DEPARTURE_DATE
except Exception:
    ORIGIN, DESTINATION, DEPARTURE_DATE = "TPE", "TYO", "2027-02-03"


URL = "https://flight.eztravel.com.tw"

ORIGIN_CODE = os.getenv("FLIGHT_ORIGIN", ORIGIN)
DESTINATION_CODE = os.getenv("FLIGHT_DESTINATION", DESTINATION)
OUTBOUND_DATE = os.getenv("FLIGHT_DATE", DEPARTURE_DATE)
RETURN_DATE = os.getenv("FLIGHT_RETURN_DATE", "")  # 空字串 = 只搜去程

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
POST_STEPS = ["transform.py", "load_mysql.py"]

city_name_map = {
    "TPE": "台北",
    "TYO": "東京",
    "KIX": "大阪",
    "ICN": "首爾",
    "BKK": "曼谷",
    "HKG": "香港",
}

MONTH_NAMES = [
    "一月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "十一月", "十二月",
]

os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/debug", exist_ok=True)

# 目前正在搜的航段（handle_response 用來檢查請求內容）
current_leg = {"origin": None, "destination": None, "date": None}
# 目前這一段已存下來的 raw 檔
leg_files = []


# ==============================
# 小工具
# ==============================

def first_visible(locator):
    """回傳 locator 裡第一個看得到的元素，找不到回傳 None。"""
    for i in range(locator.count()):
        item = locator.nth(i)
        if item.is_visible():
            return item
    return None


def make_response_handler():
    def handle_response(response):
        if "/apiv2/flight/list" not in response.url:
            return

        print("\n========== API FOUND ==========")
        print("URL:", response.url)
        print("Status:", response.status)
        print("METHOD:", response.request.method)
        post_data = response.request.post_data
        print("POST DATA:", post_data)

        # 軟檢查：請求內容有沒有包含這一段的出發地 / 目的地
        if post_data:
            for key in ("origin", "destination"):
                code = current_leg[key]
                if code and code not in post_data:
                    print(f"WARNING: POST DATA 裡找不到 {key} = {code}")

        try:
            data = response.json()
            # The results page can issue delayed requests from the previous leg.
            # Only persist a response whose itinerary actually matches the leg
            # currently being collected.
            routings = (data.get("data") or {}).get("routings") or []
            expected_origin = current_leg.get("origin")
            expected_destination = current_leg.get("destination")
            expected_date = current_leg.get("date")
            matching_routing = False
            for routing in routings:
                sectors = routing.get("sectors") or []
                if not sectors:
                    continue
                first = sectors[0]
                if (
                    (
                        first.get("departureCityCode") == expected_origin
                        or first.get("departureAirportCode") == expected_origin
                    )
                    and (
                        first.get("arrivalCityCode") == expected_destination
                        or first.get("arrivalAirportCode") == expected_destination
                    )
                    and first.get("departureDate") == expected_date
                ):
                    matching_routing = True
                    break
            if not matching_routing:
                print(
                    "Ignoring API response that does not match current leg:",
                    expected_origin, expected_destination, expected_date,
                )
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

            raw_file = (
                f"data/raw/flight_"
                f"{current_leg['origin']}_"
                f"{current_leg['destination']}_"
                f"{timestamp}.json"
            )
            with open(raw_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            leg_files.append(raw_file)
            print("Response saved:", raw_file)
        except Exception as e:
            print("Cannot parse JSON:", e)

    return handle_response


def wait_for_api(page, timeout_s=60, settle_s=5):
    """等到這一段的 API 回應存檔。回傳是否成功。頁面被關閉時不會崩潰。"""
    try:
        for _ in range(timeout_s):
            if leg_files:
                break
            page.wait_for_timeout(1000)
        if leg_files and settle_s:
            page.wait_for_timeout(settle_s * 1000)  # API 可能分批回傳
    except PlaywrightError as e:
        print("等待期間頁面或瀏覽器被關閉:", str(e).splitlines()[0])
    return bool(leg_files)


def run_post_steps(origin, destination, date, raw_file):
    """跑 transform / load_mysql，環境變數給這一段的資訊。"""
    env = os.environ.copy()
    env["FLIGHT_ORIGIN"] = origin
    env["FLIGHT_DESTINATION"] = destination
    env["FLIGHT_DATE"] = date
    env["FLIGHT_RETURN_DATE"] = RETURN_DATE
    env["FLIGHT_TRIP_OUTBOUND_DATE"] = OUTBOUND_DATE
    env["FLIGHT_TRIP_ORIGIN"] = ORIGIN_CODE
    env["FLIGHT_TRIP_DESTINATION"] = DESTINATION_CODE
    env["FLIGHT_RAW_FILE"] = os.path.abspath(raw_file)

    for script in POST_STEPS:
        path = os.path.join(SRC_DIR, script)

        print("\nRunning:", script)

        if script == "transform.py":
            result = subprocess.run(
                [sys.executable, path, os.path.abspath(raw_file)],
                env=env,
            )
        else:
            result = subprocess.run(
                [sys.executable, path],
                env=env,
            )

        if result.returncode != 0:
            print("Step failed:", script)
            return False
    return True


# ==============================
# 選城市 / 選日期
# ==============================

def pick_city(page, input_box, name, code, tag):
    """
    在輸入框輸入城市，並從下拉選單選一個項目。
    不假設選單文字格式，依序嘗試：
      1. 「{name}(任何)」  2. 「{name}」  3. 以 {name} 開頭的任何文字
    """
    input_box.click()
    input_box.fill("")
    input_box.press_sequentially(name, delay=150)  # 真的按鍵才會觸發自動完成
    page.wait_for_timeout(2000)

    print(f"[{tag}] input before selection:", input_box.input_value())

    # ezTravel keeps the regional tabs open while typing. The initial list can
    # still show Taiwan cities, so select the region before looking for the city.
    region_by_code = {
        "TYO": "日韓", "KIX": "日韓", "ICN": "日韓",
        "BKK": "東南亞", "HKG": "港澳大陸",
    }
    region = region_by_code.get(code)
    if region:
        region_tab = first_visible(page.get_by_text(region, exact=True))
        if region_tab:
            region_tab.click()
            page.wait_for_timeout(800)

    # Match the city label after choosing its region. Avoid prefix matches across
    # the whole page, which can click promotional links such as flight + hotel.
    candidates = [
        page.get_by_text(f"{name}({code})", exact=True),
        page.get_by_text(f"{name} ( {code} )", exact=True),
        page.get_by_text(f"{name}(任何)", exact=True),
        page.get_by_text(f"{name} (任何)", exact=True),
        page.get_by_text(name, exact=True),
    ]
    item = next((first_visible(candidate) for candidate in candidates
                 if first_visible(candidate)), None)
    if not item:
        # Airport/city entries may include a suffix such as 成田 or 羽田.
        # Accept those labels only inside the autocomplete panel directly below
        # this input, so a page-wide Tokyo link can never be mistaken for one.
        input_box_rect = input_box.bounding_box()
        if input_box_rect:
            prefix_matches = page.get_by_text(
                re.compile(rf"^{re.escape(name)}")
            )
            nearby = []
            for i in range(prefix_matches.count()):
                candidate = prefix_matches.nth(i)
                if not candidate.is_visible():
                    continue
                rect = candidate.bounding_box()
                if not rect:
                    continue
                if (
                    input_box_rect["y"] + input_box_rect["height"] - 2
                    <= rect["y"]
                    <= input_box_rect["y"] + 340
                    and input_box_rect["x"] - 20
                    <= rect["x"]
                    <= input_box_rect["x"] + 700
                ):
                    nearby.append((rect["width"] * rect["height"], candidate))
            if nearby:
                nearby.sort(key=lambda match: match[0])
                item = nearby[0][1]
    if item:
        print(f"[{tag}] click city option:", item.inner_text().strip())
        item.click()
        page.wait_for_timeout(1000)
        selected = input_box.input_value().strip()
        print(f"[{tag}] input after selection:", selected)
        if name not in selected and code not in selected:
            raise RuntimeError(
                f"[{tag}] city selection was not applied: {selected!r}"
            )
        return

    shot = f"data/debug/{tag}_{name}.png"
    page.screenshot(path=shot)
    print(f"[{tag}] 找不到選項，已存截圖:", shot)
    try:
        print(page.locator("li").all_inner_texts())
    except Exception:
        pass
    raise RuntimeError(
        f"[{tag}] cannot find an exact autocomplete option for {name} ({code})"
    )


def pick_date_in_open_calendar(page, target):
    """日曆已經打開的情況下，往後翻月直到目標日期出現，再點選。"""
    iso = target.strftime("%Y-%m-%d")
    slash = target.strftime("%Y/%m/%d")
    day = page.locator(
        f'[role="gridcell"][aria-label*="{target.year}年{target.month}月{target.day}日"], '
        f'[data-date="{iso}"], [title="{iso}"], '
        f'[aria-label*="{iso}"], [aria-label*="{slash}"]'
    )
    next_month = page.get_by_text("Next Month", exact=True)

    for _ in range(24):
        if first_visible(day):
            break
        btn = first_visible(next_month)
        if not btn:
            break
        btn.click()
        page.wait_for_timeout(600)

    target_cell = first_visible(day)
    if not target_cell:
        page.screenshot(path="data/debug/date_not_found.png")
        with open("data/debug/date_not_found.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        cells = page.locator('[role="gridcell"]')
        print("DEBUG gridcell 數量:", cells.count())
        print(
            "DEBUG gridcell 範例 aria-label:",
            [cells.nth(i).get_attribute("aria-label") for i in range(min(5, cells.count()))],
        )
        print("DEBUG 'Next Month' 數量:", page.get_by_text("Next Month", exact=True).count())
        print("DEBUG 已存 data/debug/date_not_found.png 和 date_not_found.html")
        raise RuntimeError(f"cannot find date on calendar: {target.date()}")

    print(
        f"已切換到 {target.year} 年 {MONTH_NAMES[target.month - 1]}，"
        f"選擇 {target.date()}"
    )
    target_cell.click()
    page.wait_for_timeout(1000)


# ==============================
# 兩段搜尋
# ==============================

def search_from_home(page, origin_code, destination_code, date_str):
    origin_name = city_name_map[origin_code]
    destination_name = city_name_map[destination_code]
    target_date = datetime.strptime(date_str, "%Y-%m-%d")

    page.goto(URL)
    print("Browser opened.")
    page.wait_for_timeout(3000)

    # 單程
    page.get_by_text("單程", exact=True).click()
    print("已選擇：單程")
    page.wait_for_timeout(1000)

    # 出發地 / 到達地
    inputs = page.locator('input[placeholder="輸入國家/城市/機場關鍵字"]')
    pick_city(page, inputs.nth(0), origin_name, origin_code, "departure")
    pick_city(page, inputs.nth(1), destination_name, destination_code, "arrival")

    # Do not submit if the site navigated away from its flight search form or
    # the reversed return route was not actually selected in the fields.
    if inputs.count() < 2:
        page.screenshot(path="data/debug/city_form_missing.png")
        raise RuntimeError("搜尋表單在選城市後消失，停止送出以避免進入其他商品頁")
    selected_origin = inputs.nth(0).input_value().strip()
    selected_destination = inputs.nth(1).input_value().strip()
    if (
        (origin_name not in selected_origin and origin_code not in selected_origin)
        or (destination_name not in selected_destination and destination_code not in selected_destination)
    ):
        page.screenshot(path="data/debug/city_selection_invalid.png")
        raise RuntimeError(
            "航線欄位與預期不符："
            f"{selected_origin!r} → {selected_destination!r}"
        )

    # 日期
    outbound = page.locator('input[placeholder="請選擇"]').nth(0)
    outbound.click()
    page.wait_for_timeout(1000)
    pick_date_in_open_calendar(page, target_date)
    print("Departure date after selection:", outbound.input_value())

    # 關閉日期選擇器
    page.mouse.click(1000, 100)
    page.wait_for_timeout(500)

    # 搜尋
    search_button = page.get_by_role("button", name="搜尋")
    print("Search button count:", search_button.count())
    search_button.click(force=True)
    print("Search button clicked!")


def switch_to_return_leg(page):
    """在去程結果頁按轉換鈕、改日期，取得回程的搜尋結果。"""
    target_date = datetime.strptime(RETURN_DATE, "%Y-%m-%d")

    # 1. 轉換出發地 / 目的地
    exchange = first_visible(page.locator("i.icon-exchange"))
    if not exchange:
        page.screenshot(path="data/debug/no_exchange_button.png")
        raise RuntimeError("找不到轉換按鈕 (i.icon-exchange)")
    exchange.click()
    print("已按轉換按鈕")
    page.wait_for_timeout(1500)

    # 2. 改成回程日期
    date_box = first_visible(page.locator(".dc-date"))
    if not date_box:
        page.screenshot(path="data/debug/no_date_box.png")
        raise RuntimeError("找不到日期欄位 (.dc-date)")
    print("目前結果頁日期:", date_box.inner_text().strip())
    cells = page.locator('[role="gridcell"]')
    calendar_open = False
    for attempt in range(2):
        date_box.click()
        try:
            cells.first.wait_for(state="visible", timeout=6000)
            calendar_open = True
            break
        except PlaywrightError:
            print(f"日曆第 {attempt + 1} 次沒有打開，重試")
    if not calendar_open:
        page.screenshot(path="data/debug/calendar_not_open.png")
        print("日曆沒有打開，已存 data/debug/calendar_not_open.png，仍嘗試繼續找日期")
    page.wait_for_timeout(1500)  # 等動畫 / 渲染完成
    pick_date_in_open_calendar(page, target_date)

    # 從這裡開始收到的 API 才算回程（清掉轉換時可能觸發的舊結果）
    leg_files.clear()

    # 3. 換日期後網站可能會自動重新搜尋，先等幾秒；沒反應就自己按搜尋
    if wait_for_api(page, timeout_s=8, settle_s=0):
        return

    search_button = first_visible(page.get_by_role("button", name="搜尋"))
    if search_button:
        print("沒有自動搜尋，按搜尋按鈕")
        search_button.click(force=True)
    else:
        page.screenshot(path="data/debug/no_search_button_on_results.png")
        print("結果頁找不到搜尋按鈕，繼續等 API")


# ==============================
# main
# ==============================

def main():
    for code in (ORIGIN_CODE, DESTINATION_CODE):
        if code not in city_name_map:
            print("Unknown city code:", code)
            sys.exit(1)

    print("==============================")
    print("ORIGIN:", ORIGIN_CODE)
    print("DESTINATION:", DESTINATION_CODE)
    print("OUTBOUND:", OUTBOUND_DATE)
    print("RETURN:", RETURN_DATE or "(不搜回程)")
    print("==============================")

    failed = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 掛在 context 上，就算結果開在新分頁也抓得到
        context.on("response", make_response_handler())
        page.on("framenavigated", lambda frame: print("NAVIGATED:", frame.url))

        try:
            # ---------- 去程 ----------
            current_leg.update(
                origin=ORIGIN_CODE, destination=DESTINATION_CODE, date=OUTBOUND_DATE
            )
            leg_files.clear()
            search_from_home(page, ORIGIN_CODE, DESTINATION_CODE, OUTBOUND_DATE)

            if wait_for_api(page):
                page.screenshot(path="data/debug/leg1_result.png")
                if not run_post_steps(
                    ORIGIN_CODE, DESTINATION_CODE, OUTBOUND_DATE, leg_files[-1]
                ):
                    failed.append("outbound post steps")
            else:
                print("去程沒有抓到 API 回應")
                failed.append("outbound scrape")

            # ---------- 回程 ----------
            if RETURN_DATE and "outbound scrape" not in failed:
                current_leg.update(
                    origin=DESTINATION_CODE, destination=ORIGIN_CODE, date=RETURN_DATE
                )
                # Search the return as its own one-way query from the homepage.
                # The result-page calendar's DOM differs from the home calendar,
                # which made the old date selector fail even when the calendar
                # was visibly open. The same verified flow used for outbound
                # also gives us an unambiguous reversed route and date.
                leg_files.clear()
                search_from_home(page, DESTINATION_CODE, ORIGIN_CODE, RETURN_DATE)
                if wait_for_api(page):
                    page.screenshot(path="data/debug/leg2_result.png")
                    if not run_post_steps(
                        DESTINATION_CODE, ORIGIN_CODE, RETURN_DATE, leg_files[-1]
                    ):
                        failed.append("return post steps")
                else:
                    print("回程沒有抓到 API 回應")
                    try:
                        page.screenshot(path="data/debug/leg2_no_api.png")
                    except PlaywrightError:
                        pass
                    failed.append("return scrape")

        except Exception as e:
            print("ERROR:", e)
            failed.append(str(e))
        finally:
            try:
                browser.close()
            except PlaywrightError:
                pass

    if failed:
        print("\nFAILED:", failed)
        sys.exit(1)

    print("\nDONE")


if __name__ == "__main__":
    main()
