// Whether the first start's window opens (docs/reference/4-app.md, "The first start"): the decision at each server
// info, apart from the window (FirstRunWindow in the app).
import Foundation

public enum FirstRun {
    /// The app's preference that the first start's window was finished with Done; absent before its first start.
    public static let setupDone = "setupDone"

    public enum Decision: Equatable {
        /// Nothing: the window stays as it is.
        case none
        /// An earlier version's setup, which had no preference (a config and a downloaded model): the setup is done.
        case setUpEarlier
        /// The window opens; the setup is not done until Done.
        case show
    }

    /// The decision for the server's model `model`: the window opens once in a run of the app (`shown`), when the
    /// setup is not done (`setupDone`, the preference) or no variant of the menu's model is downloaded or downloading.
    /// An earlier version's setup (no preference yet, but a config when the app started and a downloaded model)
    /// counts as done. Without a model with variants in the info (an older server, or none yet), nothing.
    public static func decide(model: ServerInfo.Model?, shown: Bool, setupDone: Bool?, configExisted: Bool) -> Decision {
        guard !shown, let m = model, let variants = m.variants, !variants.isEmpty, m.name != nil, m.catalog != nil
        else { return .none }
        let hasModel = variants.contains { $0.downloaded || $0.downloading == true }
        if setupDone == nil && configExisted && hasModel { return .setUpEarlier }
        return setupDone == true && hasModel ? .none : .show
    }
}
