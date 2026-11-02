// Where a setting's value lives in the config, what is in force, and where that comes from: one rule for every
// setting of the settings window, the server's, the models', the adapters' and the app's (docs/design.md,
// "Settings"). The user's value is at the owner; without one, the value comes from the level under it:
//   an adapter's setting: the adapter's entry, then its manifest (its info's context), then the fallback (the
//     setting's default);
//   any other setting: the owner's default (SettingInfo.default).
// A value equal to the one under it is no change: it is not written (edit), and one already in the file does not
// count as changed. The app's other choices (the hotkeys, the language, the microphone, the model, a variant, a prompt,
// a language's lists, an adapter's switch) follow the same rule: each is a ConfigChange made here, with its path from
// here, and a value equal to its default takes the key out (docs/design.md, "The config file over versions").
import Foundation

/// One change of the config file: a value written at a path, or the value at a path taken out. ConfigStore.apply
/// writes it.
public enum ConfigChange: Equatable {
    case set([String], Any)
    case remove([String])

    public var path: [String] {
        switch self {
        case let .set(p, _), let .remove(p): return p
        }
    }

    public static func == (a: ConfigChange, b: ConfigChange) -> Bool {
        switch (a, b) {
        case let (.set(p, x), .set(q, y)): return p == q && SettingStore.same(x, y)
        case let (.remove(p), .remove(q)): return p == q
        default: return false
        }
    }
}

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
    /// Where the config keeps the app's choices: the menu's model, the language, the microphone, a hotkey, whether an
    /// adapter is on, a model's chosen variant and its own prompt.
    public static let modelPath = ["model"]
    public static let languagePath = ["language"]
    public static let microphonePath = ["microphone"]
    public static func keyPath(isPrivate: Bool) -> [String] { [isPrivate ? "privateDictationKey" : "dictationKey"] }
    public static func enabledPath(of adapter: String) -> [String] { ["adapters", adapter, "enabled"] }
    public static func variantPath(of model: String) -> [String] { ["models", model, "variant"] }
    public static func promptPath(of model: String) -> [String] { ["models", model, "prompt"] }

    /// A language's list in the config: its prompt notes, one a line, or its hesitation sounds, separated by commas.
    /// The code "*" (every) holds the notes of every language.
    public enum LanguageList: String {
        case notes, fillers
        public static let every = "*"
        public func path(of code: String) -> [String] { ["languages", code, rawValue] }
        /// The list's default: the server's (server/languages.json) for the language `code`, or every language's
        /// notes; nil when the server has not answered.
        public func defaults(of code: String, in info: ServerInfo?) -> [String]? {
            guard let info else { return nil }
            if code == Self.every { return info.commonNotes ?? [] }
            let l = info.languages.first { $0.code == code }
            return (self == .notes ? l?.notes : l?.fillers) ?? []
        }
        /// The list as the settings window shows it.
        public func text(_ items: [String]) -> String { items.joined(separator: self == .notes ? "\n" : ", ") }
        /// The list from what is typed: trimmed, the empty items out.
        public func items(_ text: String) -> [String] {
            text.components(separatedBy: self == .notes ? "\n" : ",")
                .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        }
    }

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

    /// The menu's model, whose settings, variant and prompt the window shows: the config's choice, else the server's
    /// default, the first of its registry (`info`); nil without either.
    public static func menuModel(in config: Config, info: ServerInfo?) -> String? { config.model ?? info?.models?.first }

    /// What is in force for `s` and where it comes from; `info`, the server's, names the menu's model when the config
    /// has none (menuModel).
    public static func state(of s: SettingInfo, in config: Config, scope: SettingScope = .owner,
                             info: ServerInfo? = nil) -> SettingState {
        let path = path(of: s, model: menuModel(in: config, info: info), scope: scope)
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
        case "string", "folder": v = .string(t)
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

    // MARK: What a choice writes

    /// What a row's edit of `s` (edit, toggle: they compare with the inherited value) changes in the file: its value
    /// written, or taken out; nil for a refused edit or when the file has that already.
    public static func change(_ edit: SettingEdit, of s: SettingInfo, scope: SettingScope = .owner,
                              in config: Config, info: ServerInfo? = nil) -> ConfigChange? {
        guard let path = path(of: s, model: menuModel(in: config, info: info), scope: scope) else { return nil }
        switch edit {
        case let .write(v): return json(v, of: s).flatMap { change(path, to: $0, default: nil, in: config) }
        case .remove: return reset(path, in: config)
        case .refuse: return nil
        }
    }

    /// The value at `path` taken out, back to its default; nil when the file has none.
    public static func reset(_ path: [String], in config: Config) -> ConfigChange? {
        config.value(path) == nil ? nil : .remove(path)
    }

    /// The change that gives `path` the value `value`: taken out when it equals `default`, else written; nil when the
    /// file has that already. A default of nil is one the app does not know yet (the server has not answered): the
    /// value is written.
    public static func change(_ path: [String], to value: Any, default d: Any?, in config: Config) -> ConfigChange? {
        let here = config.value(path)
        if let d, same(value, d) { return here == nil ? nil : .remove(path) }
        if let here, same(here, value) { return nil }
        return .set(path, value)
    }

    /// A hotkey chosen: a key, or nil for none.
    public static func hotkey(_ key: TapKeyChoice?, isPrivate: Bool, in config: Config) -> ConfigChange? {
        let d = isPrivate ? Config.defaultPrivateDictationKey : Config.defaultDictationKey
        return change(keyPath(isPrivate: isPrivate), to: TapKeyChoice.configValue(key), default: d.rawValue, in: config)
    }

    /// The speech's language chosen ("" for any); its default is macOS's language.
    public static func language(_ code: String, in config: Config) -> ConfigChange? {
        change(languagePath, to: code, default: config.systemLanguage, in: config)
    }

    /// The microphone chosen (MicrophoneChoice.value); the default is the Mac's own.
    public static func microphone(_ value: String, in config: Config) -> ConfigChange? {
        change(microphonePath, to: value, default: Config.builtInMicrophone, in: config)
    }

    /// The menu's model chosen; the default is the server's, the first of its registry.
    public static func model(_ name: String, info: ServerInfo?, in config: Config) -> ConfigChange? {
        change(modelPath, to: name, default: info?.models?.first, in: config)
    }

    /// An adapter turned on or off; one the file does not turn on is off.
    public static func adapter(_ name: String, enabled: Bool, in config: Config) -> ConfigChange? {
        change(enabledPath(of: name), to: enabled, default: false, in: config)
    }

    /// The variant of `model` chosen among the server's `variants`; the default is the catalog's.
    public static func variant(_ id: String, of model: String, variants: [ServerInfo.Variant]?,
                               in config: Config) -> ConfigChange? {
        change(variantPath(of: model), to: id, default: variants?.first { $0.default == true }?.id, in: config)
    }

    /// The prompt of `model` saved; the default is the catalog's prompt (`catalog`, nil when it is not known).
    public static func prompt(_ text: String, of model: String, catalog: String?, in config: Config) -> ConfigChange? {
        change(promptPath(of: model), to: text, default: catalog, in: config)
    }

    /// A language's list saved, from what is typed; the default is the server's (LanguageList.defaults).
    public static func list(_ list: LanguageList, of code: String, text: String, info: ServerInfo?,
                            in config: Config) -> ConfigChange? {
        change(list.path(of: code), to: list.items(text), default: list.defaults(of: code, in: info), in: config)
    }

    /// Whether two values of the file are the same value: the same string, number or boolean (true is not 1), or the
    /// same list of strings.
    static func same(_ a: Any?, _ b: Any?) -> Bool {
        if let x = a as? [String], let y = b as? [String] { return x == y }
        guard let x = SettingValue(json: a), let y = SettingValue(json: b) else { return false }
        return x == y
    }
}
