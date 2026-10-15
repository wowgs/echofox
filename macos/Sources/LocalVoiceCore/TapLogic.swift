// The hotkey's logic, apart from the event monitors (TapKey in the app): a tap of one modifier key alone, pressed and
// released within Tuning.longestTapSeconds with no other key, modifier or click in between.
import Foundation

public struct TapLogic {
    public enum Event {
        case flags(keyCode: UInt16, raw: UInt, timestamp: TimeInterval)
        case keyOrClick
    }

    public static let rightOption: UInt16 = 61     // kVK_RightOption
    public static let rightOptionMask: UInt = 0x40  // NX_DEVICERALTKEYMASK: the right Option is down
    public static let leftOptionMask: UInt = 0x20   // NX_DEVICELALTKEYMASK
    public static let otherModifiers: UInt = 0x0002_0000 | 0x0004_0000 | 0x0010_0000  // Shift, Control, Command

    public let keyCode: UInt16, downMask: UInt, longest: TimeInterval
    private var downAt: TimeInterval?
    private var spoiled = false

    public init(keyCode: UInt16 = TapLogic.rightOption, downMask: UInt = TapLogic.rightOptionMask,
                longest: TimeInterval = Tuning.longestTapSeconds) {
        self.keyCode = keyCode
        self.downMask = downMask
        self.longest = longest
    }

    /// The key's name for the menu.
    public var keyName: String { keyCode == TapLogic.rightOption ? "the right Option" : "key \(keyCode)" }

    /// Feeds one event; true when it completes a tap.
    public mutating func feed(_ e: Event) -> Bool {
        switch e {
        case .keyOrClick:
            if downAt != nil { spoiled = true }
            return false
        case let .flags(code, raw, t):
            guard code == keyCode else {
                if downAt != nil { spoiled = true }
                return false
            }
            if raw & downMask != 0 {
                downAt = t
                spoiled = raw & TapLogic.otherModifiers != 0 || raw & TapLogic.leftOptionMask != 0
                return false
            }
            defer { downAt = nil }
            guard let d = downAt else { return false }
            return !spoiled && t - d <= longest
        }
    }
}
