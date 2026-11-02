// The lines of the menu bar's menu, top to bottom (MenuBar shows them): an update's line while one waits, the
// settings lines in SettingsLayout.menu's order, then Check for Updates…, Settings… and Quit. SettingsLayout places
// the settings lines; the frame around them is fixed here. MenuBar has a view for each line (an exhaustive switch),
// and echofox-tests checks that every id of SettingsLayout.menu is a MenuSetting.
import Foundation

/// The settings lines that the menu can show; the raw value is the id in SettingsLayout.places.
public enum MenuSetting: String, CaseIterable {
    /// Shown only while a permission is missing.
    case permissions
    case microphone, inputVolume, labelRecordings
}

public enum MenuLine: Equatable {
    case update, setting(MenuSetting), separator, checkForUpdates, settings, quit

    /// The menu's lines. `update`: whether an update waits for the user.
    public static func all(update: Bool) -> [MenuLine] {
        (update ? [.update, .separator] : []) + SettingsLayout.menu.compactMap(MenuSetting.init).map(MenuLine.setting)
            + [.separator, .checkForUpdates, .settings, .quit]
    }
}
