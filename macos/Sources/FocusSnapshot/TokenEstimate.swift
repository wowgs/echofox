// The estimate of a text's tokens for the model, the same as the server's (server/budget.py): the characters by kind,
// each kind weighed by the model's tokens per character of it (its catalog entry's tokenWeights, which the server's
// info gives). The snapshot reads the screen up to the token budget of the adapters that ask for it.
import Foundation

public struct TokenEstimate: Equatable {
    public static let kinds = ["cyrillic", "latin", "digit", "space", "other"]
    /// For a model without weights: a token per 3.4 characters of any kind (server/budget.py, FALLBACK).
    public static let fallback = TokenEstimate(weights: Dictionary(uniqueKeysWithValues: kinds.map { ($0, 0.295) }))

    public let weights: [String: Double]

    public init(weights: [String: Double]) { self.weights = weights }

    /// The model's weights, or the fallback when it has none.
    public init(_ weights: [String: Double]?) {
        self = weights.map { $0.isEmpty ? .fallback : TokenEstimate(weights: $0) } ?? .fallback
    }

    static func kind(_ c: Unicode.Scalar) -> String {
        switch c.value {
        case 0x0400...0x04FF: return "cyrillic"
        case 0x41...0x5A, 0x61...0x7A: return "latin"
        case 0x30...0x39: return "digit"
        default: return c.properties.isWhitespace ? "space" : "other"
        }
    }

    /// The estimated tokens of the text.
    public func count(_ text: String) -> Int {
        var by: [String: Int] = [:]
        for c in text.unicodeScalars { by[Self.kind(c), default: 0] += 1 }
        return Int((by.reduce(0.0) { $0 + (weights[$1.key] ?? 0) * Double($1.value) }).rounded(.up))
    }
}
