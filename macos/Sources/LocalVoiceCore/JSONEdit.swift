// Changes one value in a JSON text and keeps the rest of the text as it was: the order of the keys, the indentation,
// the line breaks. The config file is the user's as much as the app's, so a click in the menu must not rewrite it.
import Foundation

public enum JSONEdit {
    /// The text with `value` at `path` (keys of nested objects). A missing key is added after the last member of its
    /// object, with that member's indentation; the objects missing on the path are made. Throws if the text is not a
    /// JSON object or a value on the path is not an object.
    public static func set(_ path: [String], to value: Any, in text: String) throws -> String {
        guard !path.isEmpty else { throw MessageError("an empty path") }
        var s = Scanner(Array(text.utf8))
        let start = s.skipSpace(0)
        guard start < s.b.count, s.b[start] == UInt8(ascii: "{") else { throw MessageError("not a JSON object") }
        let (range, replacement) = try s.edit(object: start, path: path[...], value: value)
        var out = s.b
        out.replaceSubrange(range, with: Array(replacement.utf8))
        return String(decoding: out, as: UTF8.self)
    }

    /// The text without the member at `path`, the rest as it was: the member goes with the comma and the space that
    /// part it from its neighbour. A missing member leaves the text as it is. Throws if the text is not a JSON object
    /// or a value on the path is not an object.
    public static func remove(_ path: [String], in text: String) throws -> String {
        guard !path.isEmpty else { throw MessageError("an empty path") }
        var s = Scanner(Array(text.utf8))
        let start = s.skipSpace(0)
        guard start < s.b.count, s.b[start] == UInt8(ascii: "{") else { throw MessageError("not a JSON object") }
        guard let range = try s.removal(object: start, path: path[...]) else { return text }
        var out = s.b
        out.removeSubrange(range)
        return String(decoding: out, as: UTF8.self)
    }

    /// `value` as JSON on one line, with Python's separators (", " and ": "), as the server writes the file.
    static func encode(_ value: Any) throws -> String {
        if let d = value as? [String: Any] {
            let members = try d.keys.sorted().map { "\(try encode($0)): \(try encode(d[$0]!))" }
            return "{" + members.joined(separator: ", ") + "}"
        }
        if let a = value as? [Any] { return "[" + (try a.map(encode)).joined(separator: ", ") + "]" }
        let data = try JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed, .withoutEscapingSlashes])
        return String(decoding: data, as: UTF8.self)
    }

    /// `value` under the keys of `path`, as nested objects.
    static func nest(_ path: ArraySlice<String>, _ value: Any) -> Any {
        path.reversed().reduce(value) { inner, key in [key: inner] }
    }

    private struct Member {
        let key: String
        let keyStart: Int
        let valueStart: Int
        let valueEnd: Int
    }

    private struct Scanner {
        let b: [UInt8]
        init(_ b: [UInt8]) { self.b = b }

        func skipSpace(_ i: Int) -> Int {
            var i = i
            while i < b.count, [0x20, 0x09, 0x0A, 0x0D].contains(b[i]) { i += 1 }
            return i
        }

        /// The range to replace and its new text.
        func edit(object start: Int, path: ArraySlice<String>, value: Any) throws -> (Range<Int>, String) {
            let (members, close) = try self.members(start)
            let key = path.first!
            if let m = members.last(where: { $0.key == key }) {  // a parser takes the last of repeated keys
                if path.count == 1 { return (m.valueStart..<m.valueEnd, try encode(value)) }
                guard b[m.valueStart] == UInt8(ascii: "{") else { throw MessageError("\(key) is not an object") }
                return try edit(object: m.valueStart, path: path.dropFirst(), value: value)
            }
            let member = "\(try encode(key)): \(try encode(nest(path.dropFirst(), value)))"
            guard let last = members.last else { return (start..<close + 1, "{" + member + "}") }
            var indent = last.keyStart
            while indent > start + 1, [0x20, 0x09, 0x0A, 0x0D].contains(b[indent - 1]) { indent -= 1 }
            let space = String(decoding: b[indent..<last.keyStart], as: UTF8.self)
            return (last.valueEnd..<last.valueEnd, "," + (space.isEmpty ? " " : space) + member)
        }

        /// The bytes to take out for the member at `path`, or nil if it is not there.
        func removal(object start: Int, path: ArraySlice<String>) throws -> Range<Int>? {
            let (members, close) = try self.members(start)
            let key = path.first!
            guard let n = members.lastIndex(where: { $0.key == key }) else { return nil }
            let m = members[n]
            if path.count > 1 {
                guard b[m.valueStart] == UInt8(ascii: "{") else { throw MessageError("\(key) is not an object") }
                return try removal(object: m.valueStart, path: path.dropFirst())
            }
            if n + 1 < members.count { return m.keyStart..<members[n + 1].keyStart }  // with its comma and the space
            if n > 0 { return members[n - 1].valueEnd..<m.valueEnd }                   // the comma before it
            return (start + 1)..<close                                                  // the only member
        }

        /// The members of the object at `start`, and the index of its closing brace.
        func members(_ start: Int) throws -> ([Member], Int) {
            var out: [Member] = []
            var i = skipSpace(start + 1)
            if i < b.count, b[i] == UInt8(ascii: "}") { return (out, i) }
            while true {
                guard i < b.count, b[i] == UInt8(ascii: "\"") else { throw MessageError("a key expected at byte \(i)") }
                let keyEnd = try stringEnd(i)
                let keyData = Data(b[i..<keyEnd])
                guard let key = try JSONSerialization.jsonObject(with: keyData, options: .fragmentsAllowed) as? String
                else { throw MessageError("a bad key at byte \(i)") }
                var j = skipSpace(keyEnd)
                guard j < b.count, b[j] == UInt8(ascii: ":") else { throw MessageError("a colon expected at byte \(j)") }
                j = skipSpace(j + 1)
                let end = try valueEnd(j)
                out.append(Member(key: key, keyStart: i, valueStart: j, valueEnd: end))
                i = skipSpace(end)
                guard i < b.count else { throw MessageError("the object does not end") }
                if b[i] == UInt8(ascii: "}") { return (out, i) }
                guard b[i] == UInt8(ascii: ",") else { throw MessageError("a comma expected at byte \(i)") }
                i = skipSpace(i + 1)
            }
        }

        func valueEnd(_ i: Int) throws -> Int {
            guard i < b.count else { throw MessageError("a value expected at the end") }
            switch b[i] {
            case UInt8(ascii: "\""):
                return try stringEnd(i)
            case UInt8(ascii: "{"):
                return try members(i).1 + 1
            case UInt8(ascii: "["):
                var j = skipSpace(i + 1)
                if j < b.count, b[j] == UInt8(ascii: "]") { return j + 1 }
                while true {
                    j = skipSpace(try valueEnd(j))
                    guard j < b.count else { throw MessageError("the array does not end") }
                    if b[j] == UInt8(ascii: "]") { return j + 1 }
                    guard b[j] == UInt8(ascii: ",") else { throw MessageError("a comma expected at byte \(j)") }
                    j = skipSpace(j + 1)
                }
            default:  // a number, true, false or null
                var j = i
                while j < b.count, ![0x20, 0x09, 0x0A, 0x0D, 0x2C, 0x5D, 0x7D].contains(b[j]) { j += 1 }
                guard j > i else { throw MessageError("a value expected at byte \(i)") }
                return j
            }
        }

        func stringEnd(_ i: Int) throws -> Int {
            var j = i + 1
            while j < b.count {
                if b[j] == UInt8(ascii: "\\") {
                    j += 2
                } else if b[j] == UInt8(ascii: "\"") {
                    return j + 1
                } else {
                    j += 1
                }
            }
            throw MessageError("a string does not end")
        }
    }
}
