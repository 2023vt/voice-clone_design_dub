import XCTest

/// Walks every screen against the mocked host and keeps a screenshot of each, so
/// the iOS app can be reviewed visually from CI (the mobile workflow exports
/// these as the `ios-screenshots` artifact). Asserts only that each screen loads.
final class ScreenshotTour: XCTestCase {
    @MainActor func testScreenshotTour() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-smoke", "-AppleLanguages", "(en)"]
        app.launch()

        XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10))
        shot(app, "01-consent")
        app.buttons["consent.no"].tap()

        let address = app.textFields["connect.url"]
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        shot(app, "02-connect")
        address.tap(); address.typeText("http://127.0.0.1:3900")
        shot(app, "03-connect-keyboard")
        if app.buttons["keyboard.done"].waitForExistence(timeout: 3) { app.buttons["keyboard.done"].tap() }
        app.swipeUp()
        app.buttons["connect.submit"].tap()

        let editor = app.textViews["speak.text"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        shot(app, "04-speak")
        editor.tap(); editor.typeText("Hello from the VoiceStudio iPhone app.")
        shot(app, "05-speak-keyboard")
        if app.buttons["keyboard.done"].waitForExistence(timeout: 3) { app.buttons["keyboard.done"].tap() }
        if app.buttons["speak.engine"].exists {
            app.buttons["speak.engine"].tap()
            shot(app, "06-engine-picker")
            if app.buttons["Close"].waitForExistence(timeout: 3) { app.buttons["Close"].tap() }
        }
        app.swipeUp()
        if app.buttons["speak.generate"].exists {
            app.buttons["speak.generate"].tap()
            _ = app.buttons["audio.play"].waitForExistence(timeout: 10)
        }
        shot(app, "07-speak-generated")

        for (tab, name) in [("Voices", "08-voices"), ("Dub", "09-dub"), ("Dictate", "10-dictate"), ("Settings", "11-settings")] {
            app.tabBars.buttons[tab].tap()
            sleep(1)
            shot(app, name)
        }
        app.swipeUp()
        shot(app, "12-settings-more")

        app.terminate()
        app.launchArguments = ["--ui-smoke", "-AppleLanguages", "(en)", "-AppleInterfaceStyle", "Light"]
        app.launch()
        sleep(2)
        shot(app, "13-relaunch-light")
    }

    @MainActor private func shot(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
