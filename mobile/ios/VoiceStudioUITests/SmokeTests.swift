import XCTest

final class SmokeTests: XCTestCase {
    @MainActor func testEveryTabRendersWhileHostInventoryIsLoading() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-smoke", "--ui-delayed-inventory", "-AppleLanguages", "(en)"]
        app.launch()
        connect(app)
        XCTAssertTrue(app.textViews["speak.text"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["page.loading"].firstMatch.exists)
        app.tabBars.buttons["Dub"].tap()
        XCTAssertTrue(app.textFields["dub.source_url"].waitForExistence(timeout: 0.5))
        app.tabBars.buttons["Voices"].tap()
        XCTAssertTrue(app.buttons["voices.create"].waitForExistence(timeout: 0.5))
        app.tabBars.buttons["Dictate"].tap()
        XCTAssertTrue(app.buttons["dictate.record"].waitForExistence(timeout: 0.5))
        app.tabBars.buttons["Settings"].tap()
        XCTAssertTrue(app.buttons["settings.language"].waitForExistence(timeout: 0.5))
    }

    @MainActor func testSearchEmptyStatesAndCompactDubHistory() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-smoke", "-AppleLanguages", "(en)"]
        app.launch()
        connect(app)
        XCTAssertTrue(app.textViews["speak.text"].waitForExistence(timeout: 5))
        app.tabBars.buttons["Voices"].tap()
        let search = app.textFields["search.field"]
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap(); search.typeText("unmatched-voice")
        XCTAssertTrue(app.staticTexts["search.empty"].exists)
        XCTAssertEqual(app.staticTexts["search.empty"].label, "No matches for \"unmatched-voice\".")
        dismissUsingDone(app)
        app.tabBars.buttons["Speak"].tap()
        app.buttons["speak.engine"].tap()
        search.tap(); search.typeText("unmatched-engine")
        XCTAssertTrue(app.staticTexts["search.empty"].exists)
        dismissUsingDone(app)
        app.buttons["Close"].tap()
        app.tabBars.buttons["Dub"].tap()
        app.buttons["dub.languages"].tap()
        search.tap(); search.typeText("unmatched-language")
        XCTAssertTrue(app.staticTexts["search.empty"].exists)
        dismissUsingDone(app)
        app.buttons["Confirm"].tap()
        let download = app.buttons["dub.download.smoke-dub"]
        for _ in 0..<4 { if download.isHittable { break }; app.swipeUp() }
        XCTAssertTrue(download.exists)
        XCTAssertTrue(app.buttons["dub.share.smoke-dub"].exists)
        XCTAssertEqual(download.label, "Download: vs-dub-test.wav")
        XCTAssertLessThanOrEqual(download.frame.width, download.frame.height * 1.5)
        XCTAssertTrue(app.staticTexts["vs-dub-test.wav"].exists)
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "2:05")).firstMatch.exists)
    }

    @MainActor private func connect(_ app: XCUIApplication) {
        XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10))
        app.buttons["consent.no"].tap()
        let address = app.textFields["connect.url"]
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        address.tap(); address.typeText("http://127.0.0.1:3900")
        dismissUsingDone(app)
        app.swipeUp()
        app.buttons["connect.submit"].tap()
    }

    @MainActor func testConsentConnectGeneratePlay() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-smoke", "-AppleLanguages", "(en)"]
        app.launch()
        XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10))
        app.buttons["consent.no"].tap()
        XCTAssertTrue(app.tabBars.buttons["Connect"].exists)
        let address = app.textFields["connect.url"]
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        address.tap(); address.typeText("http://127.0.0.1:3900")
        dismissUsingDone(app)
        app.swipeUp()
        app.buttons["connect.submit"].tap()
        let editor = app.textViews["speak.text"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        XCTAssertEqual(app.alerts.count, 0)
        XCTAssertEqual(app.sheets.count, 0)
        let engine = app.buttons["speak.engine"]
        XCTAssertTrue(engine.waitForExistence(timeout: 5))
        engine.tap()
        let preset = app.buttons["choice.option.kittentts"]
        XCTAssertTrue(preset.waitForExistence(timeout: 5))
        XCTAssertTrue(preset.label.contains("KittenTTS"))
        XCTAssertFalse(app.buttons["choice.option.unavailable"].isEnabled)
        preset.tap()
        let rowHeight = engine.frame.height
        engine.tap()
        let longName = "OuteTTS (MLX Audio, Apple Silicon)"
        let longOption = app.buttons["choice.option.mlx-audio"]
        XCTAssertTrue(longOption.waitForExistence(timeout: 5))
        XCTAssertEqual(longOption.label, longName)
        longOption.tap()
        XCTAssertEqual(engine.value as? String, longName)
        XCTAssertEqual(engine.frame.height, rowHeight, accuracy: 1)
        app.buttons["speak.language"].tap()
        let search = app.textFields["search.field"]
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap(); search.typeText("Spanish")
        XCTAssertTrue(app.buttons["choice.option.spanish"].exists)
        app.buttons["Close"].tap()
        editor.tap(); editor.typeText("VoiceStudio smoke test")
        dismissUsingDone(app)
        app.swipeUp()
        app.buttons["speak.generate"].tap()
        let play = app.buttons["audio.play"]
        XCTAssertTrue(play.waitForExistence(timeout: 10))
        play.tap()
        XCTAssertEqual(play.label, "Pause")
        XCTAssertTrue(app.staticTexts["0:01"].exists)
    }

    @MainActor func testKeyboardDismissalAcrossFormsAndSearch() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-smoke", "-AppleLanguages", "(en)"]
        app.launch()
        XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10))
        app.buttons["consent.no"].tap()
        let address = app.textFields["connect.url"]
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        address.tap(); address.typeText("http://127.0.0.1:3900")
        // A field tap must retain focus; a tap on surrounding chrome dismisses it.
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        app.navigationBars.firstMatch.tap()
        assertKeyboardDismissed(app)
        address.tap(); address.typeText("\n")
        assertKeyboardDismissed(app)
        app.swipeUp()
        app.buttons["connect.submit"].tap()
        let editor = app.textViews["speak.text"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        editor.tap(); editor.typeText("An editable multiline message\nwith a second line")
        dismissUsingDone(app)
        app.swipeUp()
        XCTAssertTrue(app.buttons["speak.generate"].isHittable)

        app.tabBars.buttons["Voices"].tap()
        app.buttons["voices.actions.smoke-profile"].tap()
        app.buttons["Rename"].tap()
        let rename = app.textFields["voices.rename.name"]
        XCTAssertTrue(rename.waitForExistence(timeout: 5))
        rename.tap(); rename.typeText(" updated\n")
        assertKeyboardDismissed(app)
        app.buttons["Cancel"].tap()
        app.buttons["Clone a voice"].tap()
        let name = app.textFields["voices.clone.name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.tap(); name.typeText("Sample voice")
        dismissUsingDone(app)
        app.buttons["Cancel"].tap()

        app.tabBars.buttons["Dub"].tap()
        let source = app.textFields["dub.source_url"]
        XCTAssertTrue(source.waitForExistence(timeout: 5))
        source.tap(); source.typeText("https://media.example/sample\n")
        assertKeyboardDismissed(app)

        app.tabBars.buttons["Settings"].tap()
        let language = app.buttons["settings.language"]
        for _ in 0..<5 {
            if language.isHittable { break }
            app.swipeUp()
        }
        language.tap()
        let search = app.textFields["search.field"]
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap(); search.typeText("English")
        dismissUsingDone(app)
        XCTAssertTrue(app.buttons["choice.option.en"].isHittable)
    }

    @MainActor private func dismissUsingDone(_ app: XCUIApplication) {
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        let done = app.buttons["keyboard.done"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        done.tap()
        assertKeyboardDismissed(app)
    }

    @MainActor private func assertKeyboardDismissed(_ app: XCUIApplication) {
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.keyboards.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 5), .completed)
    }
}
