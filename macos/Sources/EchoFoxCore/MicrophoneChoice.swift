// What the config's "microphone" means among the Mac's inputs: "builtin" (the default: the Mac's own microphone,
// whatever macOS's input is), "system" (macOS's input, which follows headsets as they come and go), or a device's UID
// (one microphone, kept when others connect). The app's Core Audio code (AudioInputs) gives the devices; this decides.
import Foundation

public enum MicrophoneChoice {
    public struct Device: Equatable {
        public let uid: String
        public let builtIn: Bool
        public init(uid: String, builtIn: Bool) { (self.uid, self.builtIn) = (uid, builtIn) }
    }

    /// The config's value that choosing `device` writes: the built-in one is "builtin", so that it stays chosen
    /// whatever its UID; any other its UID.
    public static func value(for device: Device) -> String {
        device.builtIn ? Config.builtInMicrophone : device.uid
    }

    /// Whether `device` is the one `choice` names (the menu's check mark); none is for "system".
    public static func names(_ choice: String, _ device: Device) -> Bool {
        choice == Config.builtInMicrophone ? device.builtIn : choice == device.uid
    }

    /// Whether `choice` is one of the choices shown: a connected device, the built-in one, or macOS's input.
    public static func isListed(_ choice: String, among devices: [Device]) -> Bool {
        choice == Config.builtInMicrophone || choice == Config.systemMicrophone || devices.contains { $0.uid == choice }
    }

    /// The device to record from, as an index into `devices`, or nil for macOS's input. A device that is gone falls
    /// back to the built-in microphone, then to macOS's input; `why` says which.
    public static func resolve(_ choice: String, among devices: [Device]) -> (index: Int?, why: String) {
        let builtIn = devices.firstIndex(where: \.builtIn)
        switch choice {
        case Config.systemMicrophone:
            return (nil, "macOS's input")
        case Config.builtInMicrophone:
            return builtIn.map { ($0, "the built-in microphone") } ?? (nil, "no built-in microphone: macOS's input")
        default:
            if let i = devices.firstIndex(where: { $0.uid == choice }) { return (i, "the chosen microphone") }
            return builtIn.map { ($0, "the chosen microphone is gone: the built-in one") }
                ?? (nil, "the chosen microphone is gone: macOS's input")
        }
    }
}
