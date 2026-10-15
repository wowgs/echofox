// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "LocalVoice",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "FocusSnapshot", targets: ["FocusSnapshot"]),
        .executable(name: "lv-snapshot", targets: ["lv-snapshot"]),
    ],
    targets: [
        .target(name: "FocusSnapshot"),
        .executableTarget(name: "lv-snapshot", dependencies: ["FocusSnapshot"]),
    ]
)
