// What the menu bar item shows (MenuBar draws it): the fox of the state (MenuBarIcon), or the crossed-out microphone
// of a problem with its words. A running dictation wins over a problem, so that the speaker sees that the app records;
// then a missing permission, then the last dictation's error, then a server that does not answer.
import Foundation

public enum MenuBarStatus: Equatable {
    /// The fox's faces: idle, recording, recording a private dictation, waiting for the text.
    public enum Fox { case idle, recording, privateDictation, processing }

    case fox(Fox)
    case problem(String)

    public static func of(recording: Bool, privateRecording: Bool, waiting: Bool, accessibility: Bool,
                          microphoneAllowed: Bool, lastError: String?, serverProblem: Bool) -> MenuBarStatus {
        if recording { return .fox(privateRecording ? .privateDictation : .recording) }
        if waiting { return .fox(.processing) }
        if !accessibility { return .problem("Accessibility permission needed") }
        if !microphoneAllowed { return .problem("Microphone permission needed") }
        if let e = lastError { return .problem(e) }
        if serverProblem { return .problem("the dictation server does not answer") }
        return .fox(.idle)
    }
}
