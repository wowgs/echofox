// Which action gets which hotkey (TapKey watches them): each action with a key from the config, in the order given.
// Two actions never share a key: when the config gives one key to two actions, the first keeps it and the other has
// none, so a tap never starts two things.
import Foundation

public enum HotkeyAssignment {
    /// The actions that keep their keys, in the order given; an action without a key, or whose key an earlier action
    /// took, is left out.
    public static func assign<Action>(_ keys: [(Action, TapKeyChoice?)]) -> [(Action, TapKeyChoice)] {
        var taken = Set<TapKeyChoice>()
        return keys.compactMap { action, key in
            guard let key, taken.insert(key).inserted else { return nil }
            return (action, key)
        }
    }
}
