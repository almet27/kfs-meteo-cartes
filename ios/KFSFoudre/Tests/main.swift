import Foundation

let now = Date(timeIntervalSince1970: 1_794_361_000)
func strike(_ id: String, ka: Double?, km: Double = 12, age: Double = 20, type: String = "cg") -> LightningStrike {
    LightningStrike(id: id, latitude: 48.0, longitude: 1.0,
        timestamp: now.timeIntervalSince1970 - age, type: type, peakCurrentKA: ka, distanceKm: km)
}
let values = [strike("negative", ka: -65), strike("positive", ka: 60),
    strike("weak", ka: 10), strike("missing", ka: nil), strike("far", ka: 100, km: 80),
    strike("old", ka: 100, age: 121), strike("future", ka: 100, age: -30),
    strike("cloud", ka: 80, type: "ic"), strike("seen", ka: 100)]
let ground = AlertPolicy(radiusKm: 50, minimumKA: 50, groundOnly: true)
let selected = ground.candidates(values, seen: ["seen"], now: now)
precondition(selected.map(\.id) == ["negative", "positive"])
let all = AlertPolicy(radiusKm: 50, minimumKA: 50, groundOnly: false)
precondition(all.candidates(values, seen: ["seen"], now: now).map(\.id) == ["cloud", "negative", "positive"])
precondition(strike("negative", ka: -65).currentLabel == "-65 kA")
precondition(strike("positive", ka: 60).currentLabel == "+60 kA")
precondition(strike("missing", ka: nil).currentLabel == "kA indisponibles")
precondition(ground.candidates([strike("invalid", ka: .nan)], seen: [], now: now).isEmpty)
print("PASS: signs, absolute current, radius, freshness, missing kA, duplicate suppression, CG/IC filtering")

func feed(at date: Date, _ events: [LightningStrike] = [], partial: Bool = false) -> LightningFeed {
    LightningFeed(schema: 1, provider: "Test fixture", collectedAt: date.timeIntervalSince1970,
        windowSeconds: 300, pollAfterSeconds: 60, state: "resultats", partial: partial, strikes: events, note: "")
}
let zone = HistoryZone(latitude: 48, longitude: 1, radius: 50)
var history = LightningHistory()
let event = strike("retained", ka: -65, age: 10)
history.ingest(feed(at: now, [event, event, strike("unknown", ka: nil)]), now: now)
precondition(history.events.count == 2, "Deduplicate overlapping five-minute results")
history.ingest(feed(at: now.addingTimeInterval(60), [event]), now: now.addingTimeInterval(60))
precondition(history.events.count == 2)
let later = now.addingTimeInterval(360)
history.ingest(feed(at: later), now: later)
precondition(history.visible(minutes: 5, center: zone, now: later).isEmpty)
let retained = history.visible(minutes: 30, center: zone, now: later)
precondition(retained.count == 2 && retained.first { $0.id == "retained" }?.peakCurrentKA == -65)
precondition(retained.first { $0.id == "unknown" }?.peakCurrentKA == nil)
precondition(retained.allSatisfy { $0.distanceKm < 0.001 }, "Recalculate distances from selected center")
let farZone = HistoryZone(latitude: 52, longitude: 13, radius: 100)
precondition(history.visible(minutes: 60, center: farZone, now: later).isEmpty)
let encoded = try JSONEncoder().encode(history)
var restored = try JSONDecoder().decode(LightningHistory.self, from: encoded)
precondition(restored.visible(minutes: 30, center: zone, now: later) == retained)
restored.prune(now: now.addingTimeInterval(3601))
precondition(restored.events.isEmpty, "Expire by observation time, not reception time")
// Stored observations must never become new alerts.
precondition(ground.candidates(retained, seen: [], now: later).isEmpty)
var gaps = LightningHistory()
gaps.ingest(feed(at: now), now: now)
gaps.ingest(feed(at: now.addingTimeInterval(600)), now: now.addingTimeInterval(600))
let coverage = gaps.coverage(minutes: 30, now: now.addingTimeInterval(600))
precondition(coverage.segments == 2 && coverage.coveredSeconds == 600 && coverage.missingSeconds == 1200)
var full = LightningHistory()
for minute in 0...59 {
    let at = now.addingTimeInterval(Double(minute) * 60)
    full.ingest(feed(at: at), now: at)
}
precondition(full.coverage(minutes: 60, now: now.addingTimeInterval(3540)).missingSeconds == 0)
var limited = LightningHistory()
limited.ingest(feed(at: now, partial: true), now: now)
precondition(limited.coverage(minutes: 30, now: now).partial)
let before = limited.windows.count
limited.ingest(feed(at: now.addingTimeInterval(-1000)), now: now)
precondition(limited.windows.count == before, "Reject stale responses")
limited.prune(now: now.addingTimeInterval(4000))
precondition(limited.coverage(minutes: 30, now: now.addingTimeInterval(4000)).coveredSeconds == 0)
precondition(zone.key == HistoryZone(latitude: 48.00001, longitude: 1.00001, radius: 50).key)
precondition(zone.key != HistoryZone(latitude: 48, longitude: 1, radius: 100).key)
print("PASS: rolling 5/30/60 minute windows, deduplication, signed/missing kA, persistence, expiration, movement, source gaps, empty successful windows, partial lists, no historical alerts")
