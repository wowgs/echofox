// swift-tools-version:5.9
import PackageDescription

// FocusSnapshot: the focus snapshot (Accessibility). EchoFoxCore: the app's logic that needs no screen and no
// permission (the config, the protocol's messages, the hotkey's logic, the app's numbers), checked by echofox-tests.
// EchoFox: the menu bar app. echofox-snapshot: the snapshot tool. echofox-tests: the checks of EchoFoxCore, an executable
// because XCTest and Swift Testing come only with Xcode (`swift run echofox-tests`).
let package = Package(
    name: "EchoFox",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "FocusSnapshot", targets: ["FocusSnapshot"]),
        .library(name: "EchoFoxCore", targets: ["EchoFoxCore"]),
        .executable(name: "echofox-snapshot", targets: ["echofox-snapshot"]),
        .executable(name: "EchoFox", targets: ["EchoFox"]),
        .executable(name: "echofox-tests", targets: ["echofox-tests"]),
    ],
    targets: [
        .target(name: "FocusSnapshot"),
        .target(name: "EchoFoxCore"),
        .executableTarget(name: "echofox-snapshot", dependencies: ["FocusSnapshot"]),
        .executableTarget(name: "EchoFox", dependencies: ["FocusSnapshot", "EchoFoxCore"]),
        .executableTarget(name: "echofox-tests", dependencies: ["EchoFoxCore"]),
    ]
)
