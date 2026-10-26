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
        .executable(name: "echofox-updater-check", targets: ["echofox-updater-check"]),
    ],
    dependencies: [
        // The updater (docs/reference/7-development.md, "Updates"); its tools for the release are pinned in pins.sh
        .package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.10.1"),
    ],
    targets: [
        .target(name: "FocusSnapshot"),
        .target(name: "EchoFoxCore"),
        .executableTarget(name: "echofox-snapshot", dependencies: ["FocusSnapshot"]),
        .executableTarget(name: "EchoFox", dependencies: ["FocusSnapshot", "EchoFoxCore",
                                                         .product(name: "Sparkle", package: "Sparkle")],
                          // Sparkle.framework is in the app's Contents/Frameworks (build-app.sh)
                          linkerSettings: [.unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@executable_path/../Frameworks"])]),
        .executableTarget(name: "echofox-tests", dependencies: ["EchoFoxCore"]),
        // Sparkle.framework next to it, where swift build puts it
        .executableTarget(name: "echofox-updater-check", dependencies: [.product(name: "Sparkle", package: "Sparkle")],
                          linkerSettings: [.unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@executable_path"])]),
    ]
)
