// The estimate of a text's tokens for the model, the same as the server's (server/budget.py): the characters by kind,
// each kind weighed by the model's tokens per character of it (its catalog entry's tokenWeights, which the server's
// read request gives). The snapshot reads the screen up to the budgets of the server's read request. Both sides check
// the same examples (shared/token-examples.json).
import Foundation

public struct TokenEstimate: Equatable {
    public static let kinds = ["cyrillic", "latin", "digit", "space", "other"]
    /// For a model without weights: a token per 3.4 characters of any kind (server/budget.py, FALLBACK).
    public static let fallback = TokenEstimate(weights: Dictionary(uniqueKeysWithValues: kinds.map { ($0, 0.295) }))
    /// What the sum loses before its ceiling (server/budget.py, SLACK): a sum that is a whole number in decimal can
    /// come out a hair over it in binary.
    static let slack = 1e-9

    public let weights: [String: Double]

    public init(weights: [String: Double]) { self.weights = weights }

    /// The model's weights, or the fallback when it has none.
    public init(_ weights: [String: Double]?) {
        self = weights.map { $0.isEmpty ? .fallback : TokenEstimate(weights: $0) } ?? .fallback
    }

    /// Whitespace is Unicode's White_Space property, as on the server (server/budget.py, WHITE_SPACE).
    static func kind(_ c: Unicode.Scalar) -> String {
        switch c.value {
        case 0x0400...0x04FF: return "cyrillic"
        case 0x41...0x5A, 0x61...0x7A: return "latin"
        case 0x30...0x39: return "digit"
        default: return c.properties.isWhitespace ? "space" : "other"
        }
    }

    /// The characters of the text by kind.
    public static func counts(_ text: String) -> [String: Int] {
        var by = Dictionary(uniqueKeysWithValues: kinds.map { ($0, 0) })
        for c in text.unicodeScalars { by[kind(c), default: 0] += 1 }
        return by
    }

    /// The estimated tokens of the text. The kinds are summed in their order, as on the server.
    public func count(_ text: String) -> Int {
        let by = Self.counts(text)
        let sum = Self.kinds.reduce(0.0) { $0 + (weights[$1] ?? 0) * Double(by[$1] ?? 0) }
        return Int((sum - Self.slack).rounded(.up))
    }
}

/// The rule of every token budget, the same as the server's (server/budget.py, take): greedy and not strict. The items
/// are taken in their order until their tokens reach the budget; the item that reaches it is taken whole, and the
/// taking stops there. No budget: every item.
public struct TokenBudget {
    public let limit: Int?
    public private(set) var used = 0

    public init(_ limit: Int?) { self.limit = limit }

    /// The budget is reached: no item more.
    public var isReached: Bool { limit.map { used >= $0 } ?? false }

    public mutating func add(_ tokens: Int) { used += tokens }
}
