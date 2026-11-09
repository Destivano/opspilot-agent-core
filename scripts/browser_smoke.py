"""Exercise the local dashboard with Playwright. Run the demo server first.

Uses installed Chrome on Windows, bundled Chromium elsewhere.
"""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run():
    with sync_playwright() as playwright:
        options = {"channel": "chrome"} if os.name == "nt" else {}
        browser = playwright.chromium.launch(headless=True, **options)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8080")
        expect(page.get_by_role("heading", name="Offboarding, with oversight.")).to_be_visible()
        page.get_by_role("button", name="Enter as requester").click()
        expect(page.locator("#identity")).to_contain_text("Requester")

        def create(employee, reason):
            page.get_by_role("button", name="New request").click()
            expect(page.locator("#request-dialog")).to_be_visible()
            page.locator('select[name="employee_id"]').select_option(employee)
            page.get_by_label("Business reason").fill(reason)
            page.get_by_role("button", name="Collect evidence").click()
            expect(page.locator("#request-dialog")).not_to_be_visible()

        create("EMP-1042", "Offboard after confirming incident ownership.")
        expect(page.locator("#detail-body .badge")).to_have_text("Policy blocked", timeout=15000)
        expect(page.locator("#detail-body")).to_contain_text("INC-882")
        expect(page.get_by_role("button", name="Approve simulation")).to_have_count(0)
        create("EMP-1043", "Final working day. Remove assigned access after approval.")
        expect(page.locator("#detail-body .badge")).to_have_text("Awaiting approval", timeout=15000)
        expect(page.get_by_role("button", name="Approve simulation")).to_have_count(0)
        page.get_by_role("button", name="Sign out").click()
        expect(page.locator("#workflow-list")).not_to_contain_text("Alex Rivera")
        page.get_by_role("button", name="Enter as approver").click()
        page.get_by_role("button", name="Approve simulation").click()
        expect(page.locator("#detail-body .badge")).to_have_text("Completed", timeout=15000)
        expect(page.locator("#detail-body")).to_contain_text("Simulation receipt")
        assert int(page.locator("#count-blocked").inner_text()) >= 1
        assert int(page.locator("#count-done").inner_text()) >= 1
        screenshot_dir = Path("test-results")
        screenshot_dir.mkdir(exist_ok=True)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshot_dir / "dashboard-desktop.png"), full_page=True)

        page.get_by_label("Search loaded requests").fill("Morgan")
        expect(page.locator(".workflow-row").first).to_contain_text("Morgan")
        page.locator(".workflow-row").first.click()
        expect(page.locator("#detail-body .badge")).to_have_text("Policy blocked")
        page.get_by_label("Search loaded requests").clear()
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("window.scrollTo(0, 0)")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile overflow"
        page.screenshot(path=str(screenshot_dir / "dashboard-mobile.png"), full_page=True)

        # User content remains text even if it resembles markup.
        page.get_by_role("button", name="Sign out").click()
        page.get_by_role("button", name="Enter as requester").click()
        create("EMP-1043", '<img src=x onerror="alert(1)"> Final day')
        expect(page.locator("#detail-body .badge")).to_have_text("Awaiting approval", timeout=15000)
        expect(page.locator("#detail-body img")).to_have_count(0)
        page.get_by_role("button", name="Sign out").click()
        page.get_by_role("button", name="Enter as approver").click()
        page.get_by_role("button", name="Reject", exact=True).click()
        expect(page.locator("#detail-body .badge")).to_have_text("Rejected")
        assert not errors, errors

        # Exercise deployed demo login UI with an intercepted session response.
        login = browser.new_page()
        login.route("**/config", lambda route: route.fulfill(json={"mode": "simulation", "authMode": "demo"}))

        def login_response(route):
            payload = json.loads(route.request.post_data)
            assert payload["username"] == "casey.requester"
            assert payload["password"] == "test-demo-password"
            route.fulfill(json={"accessToken": "local-requester", "expiresIn": 900})

        login.route("**/login", login_response)
        login.route("**/logout", lambda route: route.fulfill(json={"ok": True}))
        login.goto("http://127.0.0.1:8080")
        login.get_by_label("Username").fill("casey.requester")
        login.get_by_label("Password", exact=True).fill("test-demo-password")
        login.get_by_role("button", name="Sign in", exact=True).click()
        expect(login.locator("#identity")).to_contain_text("Requester")
        assert login.evaluate("localStorage.length + sessionStorage.length") == 0
        login.get_by_role("button", name="Sign out").click()
        expect(login.locator("#login-panel")).to_be_visible()
        browser.close()
        print(
            "Browser smoke passed: request, block, separate approval, receipt, rejection, search, mobile, escaped input."
        )


if __name__ == "__main__":
    run()
