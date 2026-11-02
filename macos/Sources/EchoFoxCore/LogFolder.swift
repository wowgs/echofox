// The folder of EchoFox's logs, under the home folder: the app's log (app.log), the server's (ServerProcess.logInHome)
// and llama-server's, which the server names (server/constants.py LOGS). Uninstall removes it.
import Foundation

public enum LogFolder {
    public static let inHome = "Library/Logs/EchoFox"
}
