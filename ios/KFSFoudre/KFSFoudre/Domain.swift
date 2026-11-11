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

struct HistoryZone: Codable, Equatable {
    let latitude: Double
    let longitude: Double
    let radius: Int
    var key: String { String(format: "%.3f,%.3f,%d", latitude, longitude, radius) }
}

struct SourceWindow: Codable, Equatable {
    let start: Double
    let end: Double
    let partial: Bool
}

struct HistoryCoverage {
    let coveredSeconds: Double
    let missingSeconds: Double
    let segments: Int
    let partial: Bool
}

struct LightningHistory: Codable {
    private(set) var events: [LightningStrike] = []
    private(set) var windows: [SourceWindow] = []
    private(set) var truncated = false
    static let retention: Double = 3600

    mutating func ingest(_ feed: LightningFeed, now: Date) {
        prune(now: now)
        let end = min(feed.collectedAt, now.timeIntervalSince1970)
        guard feed.collectedAt.isFinite, abs(feed.collectedAt - now.timeIntervalSince1970) <= 180,
              feed.windowSeconds == 300 else { return }
        // A successful empty response still covers its five-minute source window.
        windows.append(SourceWindow(start: end - 300, end: end, partial: feed.partial))
        var byID = Dictionary(events.map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
        for event in feed.strikes {
            guard valid(event), event.timestamp >= feed.collectedAt - 300,
                  event.timestamp <= now.timeIntervalSince1970 + 10 else { continue }
            byID[event.id] = event
        }
        events = byID.values.sorted { $0.timestamp > $1.timestamp }
        if events.count > 60000 { events = Array(events.prefix(60000)); truncated = true }
        prune(now: now)
    }

    mutating func prune(now: Date) {
        let cutoff = now.timeIntervalSince1970 - Self.retention
        events.removeAll { !valid($0) || $0.timestamp < cutoff || $0.timestamp > now.timeIntervalSince1970 + 10 }
        windows.removeAll { !$0.start.isFinite || !$0.end.isFinite || $0.end < cutoff || $0.end > now.timeIntervalSince1970 + 10 }
        if windows.isEmpty { truncated = false }
    }

    func visible(minutes: Int, center: HistoryZone, now: Date) -> [LightningStrike] {
        let cutoff = now.timeIntervalSince1970 - Double(min(60, max(5, minutes))) * 60
        return events.compactMap { event in
            guard valid(event), event.timestamp >= cutoff, event.timestamp <= now.timeIntervalSince1970 + 10 else { return nil }
            let distance = Self.distance(center.latitude, center.longitude, event.latitude, event.longitude)
            guard distance <= Double(center.radius) else { return nil }
            return LightningStrike(id: event.id, latitude: event.latitude, longitude: event.longitude,
                timestamp: event.timestamp, type: event.type, peakCurrentKA: event.peakCurrentKA, distanceKm: distance)
        }.sorted { $0.timestamp > $1.timestamp }
    }

    func coverage(minutes: Int, now: Date) -> HistoryCoverage {
        let duration = Double(min(60, max(5, minutes))) * 60
        let end = now.timeIntervalSince1970, start = end - duration
        let ranges = windows.filter { $0.end > start && $0.start < end }
            .map { (max(start, $0.start), min(end, $0.end)) }.sorted { $0.0 < $1.0 }
        var total = 0.0, lastStart = 0.0, lastEnd = 0.0, count = 0
        for interval in ranges {
            if count == 0 { lastStart = interval.0; lastEnd = interval.1; count = 1 }
            else if interval.0 <= lastEnd + 1 { lastEnd = max(lastEnd, interval.1) }
            else { total += lastEnd - lastStart; lastStart = interval.0; lastEnd = interval.1; count += 1 }
        }
        if count > 0 { total += lastEnd - lastStart }
        total = min(duration, max(0, total))
        return HistoryCoverage(coveredSeconds: total, missingSeconds: duration - total, segments: count,
            partial: truncated || windows.contains { $0.partial && $0.end > start && $0.start < end })
    }

    private func valid(_ event: LightningStrike) -> Bool {
        !event.id.isEmpty && event.timestamp.isFinite && event.latitude.isFinite && event.longitude.isFinite &&
        abs(event.latitude) <= 90 && abs(event.longitude) <= 180 && ["cg", "ic"].contains(event.type) &&
        (event.peakCurrentKA == nil || event.peakCurrentKA!.isFinite)
    }
    static func distance(_ lat1: Double, _ lon1: Double, _ lat2: Double, _ lon2: Double) -> Double {
        let rad = Double.pi / 180
        let a = pow(sin((lat2 - lat1) * rad / 2), 2) + cos(lat1 * rad) * cos(lat2 * rad) * pow(sin((lon2 - lon1) * rad / 2), 2)
        return 6371 * 2 * atan2(sqrt(max(0, a)), sqrt(max(0, 1 - a)))
    }
}

struct HistoryArchive: Codable {
    var gps = LightningHistory()
    var remote = LightningHistory()
    var remoteZone: HistoryZone?
    var remoteName = ""
}
