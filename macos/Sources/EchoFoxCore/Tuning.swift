// The app's own numbers, named in one place. The numbers it shares with the dictation server (the audio format, the
// wait for the text, the longest recording) come from the server's info message (ServerInfo); the server's port comes
// from the config file. Not tuned unless noted.
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
    /// the server looks at the file every 2 s (server/settings.py CONFIG_CHECK_S). If a recording runs, the server
    /// applies the change after it, and the next app switch older than serverInfoMaxAgeSeconds picks it up.
    public static let serverConfigApplySeconds: TimeInterval = 3
    /// How often the app looks at the config file for a change from elsewhere (ConfigStore); the server looks as often
    /// (server/settings.py, CONFIG_CHECK_S).
    public static let configCheckSeconds: TimeInterval = 2
    /// The silence stop when the config does not set one.
    public static let silenceStopSeconds: TimeInterval = 60
    /// How often the recording looks for silence.
    public static let silenceCheckSeconds: TimeInterval = 1
    /// The menu: how much of an adapter's error it shows.
    public static let menuErrorChars = 100
    /// The microphone tap's buffer, in frames of the input format (about 85 ms at 48 kHz).
    public static let recorderBufferFrames: UInt32 = 4096
    /// The longest tap of the hotkey that counts as a tap, in seconds.
    public static let longestTapSeconds: TimeInterval = 0.6
    /// The labeling window: its share of the screen's width and height, its smallest size, and its distance from
    /// the screen's edges, in points.
    public static let labelWindowWidthShare = 1.0 / 3
    public static let labelWindowHeightShare = 0.45
    public static let labelWindowMinWidth = 420.0
    public static let labelWindowMinHeight = 320.0
    public static let labelWindowMargin = 16.0
    /// The defaults the app uses until the server's info arrives (the server's own values: server/constants.py).
    public static let defaultSampleRate = 16000
    public static let defaultTextWaitSeconds: TimeInterval = 180
}
