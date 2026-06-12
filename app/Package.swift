// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "Squawk",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "Squawk", path: "Sources/Squawk")
    ]
)
