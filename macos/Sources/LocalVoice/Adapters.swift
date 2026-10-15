// Which adapters the dictation server has enabled (it answers {"type": "adapters"}; server/adapters/registry.py), and
// so which apps the app takes the full focus snapshot of and which Electron apps it asks to build their accessibility
// tree. With no adapter enabled (the base mode), the app takes only the focused element and builds no tree.
import Foundation

final class Adapters {
    struct Info: Decodable {
        let name: String
        let enabled: Bool
        let apps: [String]
        let electronTree: Bool
        let error: String?
    }
    private struct Reply: Decodable { let adapters: [Info] }

    private(set) var list: [Info] = []
    private(set) var asked: Date?
    var onChange: () -> Void = {}

    /// Apps whose focus an enabled adapter reads.
    var snapshotApps: Set<String> { Set(list.filter(\.enabled).flatMap(\.apps)) }
    /// Electron apps whose accessibility tree an enabled adapter needs.
    var treeApps: Set<String> { Set(list.filter { $0.enabled && $0.electronTree }.flatMap(\.apps)) }

    /// Asks the server, unless it was asked less than `minimum` seconds ago.
    func refresh(_ url: URL, minimum: TimeInterval = 0) {
        if let a = asked, Date().timeIntervalSince(a) < minimum { return }
        asked = Date()
        let task = URLSession.shared.webSocketTask(with: url)
        task.resume()
        task.send(.string(#"{"type":"adapters"}"#)) { _ in }
        task.receive { [weak self] result in
            defer { task.cancel(with: .normalClosure, reason: nil) }
            guard case .success(let m) = result else {
                Log.write("adapters: the server did not answer")
                return
            }
            let data: Data
            switch m {
            case .string(let s): data = Data(s.utf8)
            case .data(let d): data = d
            @unknown default: return
            }
            guard let reply = try? JSONDecoder().decode(Reply.self, from: data) else { return }
            DispatchQueue.main.async {
                guard let self else { return }
                let before = self.list.map { "\($0.name)=\($0.enabled)" }
                self.list = reply.adapters
                let after = self.list.map { "\($0.name)=\($0.enabled)" }
                if before != after {
                    Log.write("adapters: " + reply.adapters.map { "\($0.name) \($0.enabled ? "on" : "off")\($0.error.map { " (\($0))" } ?? "")" }.joined(separator: ", "))
                }
                self.onChange()
            }
        }
    }
}
