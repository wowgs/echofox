// The hotkeys' logic, apart from the event monitors (TapKey in the app): a tap of one modifier key alone, pressed and
// released within Tuning.longestTapSeconds with no other key, modifier or click in between. A shortcut with the key
// (⌘C with the right Command) is no tap: the other key spoils it.
import Foundation

/// A modifier key a hotkey may be: the right-hand ones, which shortcuts use less. The codes are from Carbon's
/// Events.h (kVK_…), the masks from IOKit's IOLLEvent.h (NX_DEVICE…KEYMASK for the key itself, NX_…MASK for its kind).
public enum TapKeyChoice: String, CaseIterable {
    case rightOption, rightCommand, rightShift, rightControl

    public var keyCode: UInt16 {
        switch self {
        case .rightOption: return 0x3D
        case .rightCommand: return 0x36
        case .rightShift: return 0x3C
        case .rightControl: return 0x3E
        }
    }

    /// The device bit that says this key is down.
    public var downMask: UInt {
        switch self {
        case .rightOption: return 0x40
        case .rightCommand: return 0x10
        case .rightShift: return 0x04
        case .rightControl: return 0x2000
        }
    }

    /// The device bit of the same key on the left: held with it, the tap is spoiled.
    var leftMask: UInt {
        switch self {
        case .rightOption: return 0x20
        case .rightCommand: return 0x08
        case .rightShift: return 0x02
        case .rightControl: return 0x01
        }
    }

    /// Its kind's flag (Option, Command, Shift, Control): the other kinds held with it spoil the tap.
    var kindMask: UInt {
        switch self {
        case .rightOption: return 0x0008_0000
        case .rightCommand: return 0x0010_0000
        case .rightShift: return 0x0002_0000
        case .rightControl: return 0x0004_0000
        }
    }

    public var title: String {
        switch self {
        case .rightOption: return "Right Option (⌥)"
        case .rightCommand: return "Right Command (⌘)"
        case .rightShift: return "Right Shift (⇧)"
        case .rightControl: return "Right Control (⌃)"
        }
    }

    static let allKinds: UInt = 0x0002_0000 | 0x0004_0000 | 0x0008_0000 | 0x0010_0000
}

public struct TapLogic {
    public enum Event {
        case flags(keyCode: UInt16, raw: UInt, timestamp: TimeInterval)
        case keyOrClick
    }

    public let key: TapKeyChoice, longest: TimeInterval
    private var downAt: TimeInterval?
    private var spoiled = false

    public init(key: TapKeyChoice = .rightOption, longest: TimeInterval = Tuning.longestTapSeconds) {
        self.key = key
        self.longest = longest
    }

    /// The flags of another kind of modifier than the key's own, for tests.
    public var otherModifiers: UInt { TapKeyChoice.allKinds & ~key.kindMask }

    /// Feeds one event; true when it completes a tap.
    public mutating func feed(_ e: Event) -> Bool {
        switch e {
        case .keyOrClick:
            if downAt != nil { spoiled = true }
            return false
        case let .flags(code, raw, t):
            guard code == key.keyCode else {
                if downAt != nil { spoiled = true }
                return false
            }
            if raw & key.downMask != 0 {
                downAt = t
                spoiled = raw & otherModifiers != 0 || raw & key.leftMask != 0
                return false
            }
            defer { downAt = nil }
            guard let d = downAt else { return false }
            return !spoiled && t - d <= longest
        }
    }
}
