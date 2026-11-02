// The app's error with words for people: a message that does not decode, a config that cannot be written, a
// microphone that does not open, a server that does not answer. Its description goes to the log and the menu.
import Foundation

public struct MessageError: Error, CustomStringConvertible {
    public let description: String
    public init(_ d: String) { description = d }
}
