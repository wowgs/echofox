// The words the app's windows show for a setting and a model: a value as its field shows it, what to enter when a
// number was refused, where an adapter's value comes from, and a size in gigabytes.
import Foundation

public enum SettingText {
    /// A value as its field shows it: a whole number without a fraction, a switch as on or off; "" for none.
    public static func value(_ v: SettingValue?) -> String {
        switch v {
        case let .number(n)?: return n == n.rounded() && abs(n) < 1e9 ? String(Int(n)) : String(n)
        case let .bool(b)?: return b ? "on" : "off"
        case let .string(s)?: return s
        default: return ""
        }
    }

    /// What to type when a number was refused, next to its field (Apple HIG, Writing: say how to enter it correctly):
    /// "Enter a number from 5 to 30."
    public static func allowedValues(_ s: SettingInfo) -> String {
        let what = s.kind == "integer" ? "a whole number" : "a number"
        let lo = s.min.map { value(.number($0)) }, hi = s.max.map { value(.number($0)) }
        let above = s.minExclusive == true, below = s.maxExclusive == true
        switch (lo, hi) {
        case let (l?, h?): return "Enter \(what) " + (above ? "above \(l)" : "from \(l)") + (below ? " and below \(h)." : " to \(h).")
        case let (l?, nil): return "Enter \(what) " + (above ? "above \(l)." : "of \(l) or more.")
        case let (nil, h?): return "Enter \(what) " + (below ? "below \(h)." : "of \(h) or less.")
        default: return "Enter \(what)."
        }
    }

    /// Where the value in force comes from, for an adapter's setting: set here, its own default (named as among the
    /// server's `adapters`), or the built-in one.
    public static func source(_ state: SettingState, adapters: [ServerInfo.Adapter]) -> String {
        if state.changed { return "Set here." }
        switch state.source {
        case let .adapter(name): return "From the \(ServerInfo.adapterTitle(name, in: adapters)) defaults."
        case .ownerDefault: return "The built-in default."
        }
    }
}

/// A size in gigabytes of 10^9 bytes, one decimal, as macOS's Finder counts them: "5.6 GB".
public func gigabytes(_ bytes: Double) -> String { String(format: "%.1f GB", bytes / 1e9) }
