// swift-tools-version:5.9
import PackageDescription

// FocusSnapshot: the focus snapshot (Accessibility). LocalVoiceCore: the app's logic that needs no screen and no
// permission (the config, the protocol's messages, the hotkey's logic, the app's numbers), checked by lv-tests.
// LocalVoice: the menu bar app. lv-snapshot: the snapshot tool. lv-tests: the checks of LocalVoiceCore, an executable
// because XCTest and Swift Testing come only with Xcode (`swift run lv-tests`).
let package = Package(
    name: "LocalVoice",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "FocusSnapshot", targets: ["FocusSnapshot"]),
        .library(name: "LocalVoiceCore", targets: ["LocalVoiceCore"]),
        .executable(name: "lv-snapshot", targets: ["lv-snapshot"]),
        .executable(name: "LocalVoice", targets: ["LocalVoice"]),
        .executable(name: "lv-tests", targets: ["lv-tests"]),
    ],
    targets: [
        .target(name: "FocusSnapshot"),
        .target(name: "LocalVoiceCore"),
        .executableTarget(name: "lv-snapshot", dependencies: ["FocusSnapshot"]),
        .executableTarget(name: "LocalVoice", dependencies: ["FocusSnapshot", "LocalVoiceCore"]),
        .executableTarget(name: "lv-tests", dependencies: ["LocalVoiceCore"]),
    ]
)
