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
