// Where a setting's value lives in the config, what is in force, and where that comes from: one rule for every
// setting of the settings window, the server's, the models', the adapters' and the app's (docs/design.md,
// "Settings"). The user's value is at the owner; without one, the value comes from the level under it:
//   an adapter's setting: the adapter's entry, then its manifest (its info's context), then the fallback (the
//     setting's default);
//   any other setting: the owner's default (SettingInfo.default).
// A value equal to the one under it is no change: it is not written (edit), and one already in the file does not
// count as changed.
import Foundation

/// Which value of a setting a row shows and writes.
public enum SettingScope: Equatable {
    /// The owner's: the section "server", the menu's model's options, the top of the config.
    case owner
    /// An adapter's setting for this adapter: its entry.
    case adapter(ServerInfo.Adapter)
}

/// Where the value in force comes from, when the config has none at this level.
public enum SettingSource: Equatable {
    /// The owner's default (the server's, the model's catalog, the app's), or an adapter setting's fallback.
    case ownerDefault
    /// The adapter's manifest.
    case adapter(String)
}

public struct SettingState: Equatable {
    /// Where the value is written; nil: nowhere (a model's setting without a model).
    public let path: [String]?
    /// The config's value here when it differs from the inherited one; nil: no change.
    public let own: SettingValue?
    /// What is in force without a value here, and where it comes from.
    public let inherited: SettingValue?
    public let source: SettingSource

    public var value: SettingValue? { own ?? inherited }
    public var changed: Bool { own != nil }
}

/// What a row does with what the user entered.
public enum SettingEdit: Equatable {
    /// Write this value at the setting's path.
    case write(SettingValue)
    /// Take the value out of the config: the inherited one is in force.
    case remove
    /// Not a value of the setting: say what to enter.
    case refuse
}

public enum SettingStore {
    public static func path(of s: SettingInfo, model: String?, scope: SettingScope = .owner) -> [String]? {
        switch scope {
        case let .adapter(a): return ["adapters", a.name, s.key]
        case .owner:
            switch s.owner {
            case "server": return ["server", s.key]
            case "model": return model.map { ["models", $0, "options", s.key] }
            case "app": return [s.key]
            default: return nil
            }
        }
    }

    public static func state(of s: SettingInfo, in config: Config, scope: SettingScope = .owner) -> SettingState {
        let path = path(of: s, model: config.model, scope: scope)
        let inherited: SettingValue?, source: SettingSource
        switch scope {
        case let .adapter(a):
            if let v = a.context?[s.key] { (inherited, source) = (v, .adapter(a.name)) }
            else { (inherited, source) = (s.default, .ownerDefault) }
        case .owner: (inherited, source) = (s.default, .ownerDefault)
        }
        let here = path.flatMap { at($0, config) }
        return SettingState(path: path, own: here == inherited ? nil : here, inherited: inherited, source: source)
    }

    /// What the text typed for `s` does: an empty field or the inherited value takes the value out; a number out of
    /// range, or not a number, is refused.
    public static func edit(_ text: String, of s: SettingInfo, state: SettingState) -> SettingEdit {
        let t = text.trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return .remove }
        let v: SettingValue
        switch s.kind {
        case "string": v = .string(t)
        case "number", "integer":
            guard let n = Double(t.replacingOccurrences(of: ",", with: ".")), s.allows(n) else { return .refuse }
            v = .number(n)
        default: return .refuse
        }
        return v == state.inherited ? .remove : .write(v)
    }

    /// What a switch turned on or off does: back to the inherited value, or that value written.
    public static func toggle(_ on: Bool, state: SettingState) -> SettingEdit {
        .bool(on) == state.inherited ? .remove : .write(.bool(on))
    }

    /// A value as the config file holds it: a whole number for an integer setting.
    public static func json(_ v: SettingValue, of s: SettingInfo) -> Any? {
        if case let .number(n) = v, s.kind == "integer" { return Int(n) }
        return v.json
    }

    /// The value at a path, or nil (none, or null).
    static func at(_ path: [String], _ config: Config) -> SettingValue? {
        SettingValue(json: config.value(path)).flatMap { $0 == .null ? nil : $0 }
    }
}
