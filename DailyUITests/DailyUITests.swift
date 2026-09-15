//
//  DailyUITests.swift
//  DailyUITests
//
//  Created by Muhammadjon on 3/11/25.
//

import XCTest

final class DailyUITests: XCTestCase {

    override func setUpWithError() throws {
        // Put setup code here. This method is called before the invocation of each test method in the class.

        // In UI tests it is usually best to stop immediately when a failure occurs.
        continueAfterFailure = false

        // In UI tests it’s important to set the initial state - such as interface orientation - required for your tests before they run. The setUp method is a good place to do this.
    }

    override func tearDownWithError() throws {
        // Put teardown code here. This method is called after the invocation of each test method in the class.
    }

    @MainActor
    func testS2NativeReaderShowsVerifiedBodyAndMetadata() throws {
        let app = launchReader(scenario: "native")
        XCTAssertTrue(app.staticTexts["S2 Reader Test Story"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textViews["article-native-body"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["article-source-button"].exists)
    }

    @MainActor
    func testS2SourceReaderShowsPublisherHandoff() throws {
        let app = launchReader(scenario: "source")
        XCTAssertTrue(app.staticTexts["S2 Reader Test Story"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Continue at the publisher"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["The publisher may require a subscription to read this story."].exists)
        XCTAssertTrue(app.buttons["article-source-button"].exists)
    }

    @MainActor
    func testS2MissingTokenPreservesStoryAndExplainsAuthentication() throws {
        let app = launchReader(scenario: "no-token")
        XCTAssertTrue(app.staticTexts["S2 Reader Test Story"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Sign in required"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["article-retry-button"].exists)
    }

    @MainActor
    func testS2OfflineAndTimeoutStatesRemainRetryable() throws {
        var app = launchReader(scenario: "offline")
        XCTAssertTrue(app.staticTexts["S2 Reader Test Story"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["You're offline"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["article-retry-button"].exists)
        app.terminate()

        app = launchReader(scenario: "timeout")
        XCTAssertTrue(app.staticTexts["S2 Reader Test Story"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["The article request timed out. Please try again."].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["article-retry-button"].exists)
    }

    @MainActor
    func testS2InvalidOriginalURLFailsClosed() throws {
        let app = launchReader(scenario: "invalid")
        XCTAssertTrue(app.staticTexts["S2 Reader Test Story"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Original source link unavailable"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Article unavailable"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["article-source-button"].exists)
    }

    @MainActor
    func testLaunchPerformance() throws {
        // This measures how long it takes to launch your application.
        measure(metrics: [XCTApplicationLaunchMetric()]) {
            XCUIApplication().launch()
        }
    }

    @MainActor
    private func launchReader(scenario: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--s2-reader-ui-test", scenario]
        app.launch()
        return app
    }
}
