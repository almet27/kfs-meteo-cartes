import Foundation

struct LightningStrike: Codable, Identifiable, Equatable {
    let id: String
    let latitude: Double
    let longitude: Double
    let timestamp: Double
    let type: String
    let peakCurrentKA: Double?
    let distanceKm: Double

    var currentLabel: String {
        guard let value = peakCurrentKA else { return "kA indisponibles" }
        return String(format: "%+.0f kA", value)
    }
    var typeLabel: String { type == "cg" ? "Nuage-sol" : "Intranuageux" }
}

struct LightningFeed: Decodable {
    let schema: Int
    let provider: String
    let collectedAt: Double
    let windowSeconds: Int
    let pollAfterSeconds: Int
    let state: String
    let partial: Bool
    let strikes: [LightningStrike]
    let note: String
}

struct AlertPolicy {
    var radiusKm: Double
    var minimumKA: Double
    var groundOnly: Bool

    func candidates(_ strikes: [LightningStrike], seen: Set<String>, now: Date) -> [LightningStrike] {
        strikes.filter { strike in
            guard let current = strike.peakCurrentKA, current.isFinite,
                  strike.distanceKm.isFinite, strike.distanceKm >= 0,
                  strike.distanceKm <= radiusKm,
                  now.timeIntervalSince1970 - strike.timestamp >= -10,
                  now.timeIntervalSince1970 - strike.timestamp <= 120,
                  !seen.contains(strike.id) else { return false }
            return abs(current) >= minimumKA && (!groundOnly || strike.type == "cg")
        }.sorted { abs($0.peakCurrentKA ?? 0) > abs($1.peakCurrentKA ?? 0) }
    }
}
