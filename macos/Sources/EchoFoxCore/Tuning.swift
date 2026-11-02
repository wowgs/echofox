// The app's own numbers, named in one place: its waits, timeouts and buffers, those of the EchoFox target too. The
// numbers it shares with the dictation server (the audio format, the wait for the text, the longest recording) come
// from the server's info message (ServerInfo); the server's port comes from the config file. The geometry of a window
// or a view stays with that view. Not tuned unless noted.
import Foundation

public enum Tuning {
    /// How often the app looks whether the Accessibility permission was granted or taken away.
    public static let permissionPollSeconds: TimeInterval = 2
    /// How old the server's info may be before an app switch asks again.
    public static let serverInfoMaxAgeSeconds: TimeInterval = 30
    /// The server's info: how long one request may take, and how long to wait before asking again after a failure.
    public static let serverInfoTimeoutSeconds: TimeInterval = 5
    public static let serverInfoRetrySeconds: TimeInterval = 3
    /// While the settings window shows the server's state, it asks the server this often (one info request on the
    /// local socket; none while the last one has not answered).
    public static let serverStatusPollSeconds: TimeInterval = 2
    /// After the menu changes the adapters in the config, the app asks for the server's info again this much later:
    /// the server looks at the file every 2 s (configCheckSeconds). If a recording runs, the server
    /// applies the change after it, and the next app switch older than serverInfoMaxAgeSeconds picks it up.
    public static let serverConfigApplySeconds: TimeInterval = 3
    /// How often the app looks at the config file for a change from elsewhere (ConfigStore); the server looks as often
    /// (shared/constants.json).
    public static let configCheckSeconds: TimeInterval = 2
    /// The silence stop when the config does not set one.
    public static let silenceStopSeconds: TimeInterval = 60
    /// How often the recording looks for silence.
    public static let silenceCheckSeconds: TimeInterval = 1
    /// The smallest capacity of the recorder's buffers, in frames of the device's format (about 85 ms at 48 kHz): the
    /// buffer that the audio unit (AUHAL) renders into and the converter's input. The unit's largest slice wins when
    /// it is larger, and this is that slice when the unit does not say.
    public static let recorderBufferFrames: UInt32 = 4096
    /// The longest tap of the hotkey that counts as a tap, in seconds.
    public static let longestTapSeconds: TimeInterval = 0.6
    /// The insertion's waits (Inserter), set by hand on 2026-10-15; only Claude Desktop was tried with them. How long a
    /// way's text may take to show in the box, for an app in front and for one in the background; how long the box's
    /// app may take to come to the front with the focus in the box; how often the box is looked at meanwhile.
    public static let insertCheckSeconds: TimeInterval = 0.5
    public static let insertBackgroundCheckSeconds: TimeInterval = 1.5
    public static let insertFocusSeconds: TimeInterval = 1.0
    public static let insertPollSeconds: TimeInterval = 0.05
    /// How long the lent clipboard stays before the speaker's contents come back: an app may read it late.
    public static let clipboardRestoreSeconds: TimeInterval = 1.0
    /// The longest one Accessibility call of the Inserter may take.
    public static let accessibilityCallSeconds: Float = 1.0
    /// The menu bar's processing ring: the time between its frames (it turns 24° each).
    public static let menuBarSpinSeconds: TimeInterval = 0.12
    /// A window that comes forward while the app was active: the Dock takes the focus for this long first, so that
    /// the app's main menu answers clicks afterwards (DockPresence.bringForward).
    public static let dockFocusSeconds: TimeInterval = 0.1
    /// The wait before the app leaves the Dock after its last window closed, for a window that follows the one that
    /// closed (DockPresence.follow).
    public static let leaveDockSeconds: TimeInterval = 0.5
    /// How often the labeling window moves its playback's progress bar.
    public static let labelProgressSeconds: TimeInterval = 0.05
    /// The defaults the app uses until the server's info arrives (the server's own values: server/constants.py).
    public static let defaultSampleRate = 16000
    public static let defaultTextWaitSeconds: TimeInterval = 180
}
