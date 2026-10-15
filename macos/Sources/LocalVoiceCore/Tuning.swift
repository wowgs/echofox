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
    /// The silence stop when the config does not set one.
    public static let silenceStopSeconds: TimeInterval = 60
    /// How often the recording looks for silence.
    public static let silenceCheckSeconds: TimeInterval = 1
    /// The menu: how much of the last text and of the last error it shows.
    public static let menuTextChars = 60
    public static let menuErrorChars = 100
    /// The microphone tap's buffer, in frames of the input format (about 85 ms at 48 kHz).
    public static let recorderBufferFrames: UInt32 = 4096
    /// The longest tap of the hotkey that counts as a tap, in seconds.
    public static let longestTapSeconds: TimeInterval = 0.6
    /// The defaults the app uses until the server's info arrives (the server's own values: server/constants.py).
    public static let defaultSampleRate = 16000
    public static let defaultTextWaitSeconds: TimeInterval = 180
}
