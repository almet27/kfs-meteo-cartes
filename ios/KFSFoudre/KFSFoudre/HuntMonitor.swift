import Foundation
import Combine
import CoreLocation
import UserNotifications
import UIKit

@MainActor
final class HuntMonitor: NSObject, ObservableObject, CLLocationManagerDelegate, UNUserNotificationCenterDelegate {
    @Published var active = false
    @Published var status = "Prêt pour une nouvelle chasse"
    @Published var problem: String?
    @Published var location: CLLocation?
    @Published var strikes: [LightningStrike] = []
    @Published var lastRefresh: Date?
    @Published var expiresAt: Date?
    @Published var radius = 50 { didSet { UserDefaults.standard.set(radius, forKey: "radius") } }
    @Published var minimumKA = 20.0 { didSet { UserDefaults.standard.set(minimumKA, forKey: "minimumKA") } }
    @Published var groundOnly = true { didSet { UserDefaults.standard.set(groundOnly, forKey: "groundOnly") } }
    @Published var token = ""
    @Published var authorization = CLAuthorizationStatus.notDetermined
    @Published var todayRequests = 0
    @Published var monthRequests = 0

    let endpoint = URL(string: "https://kfs-meteo-ia.alain-leprevost.workers.dev/mobile/v1/lightning")!
    private let manager = CLLocationManager()
    private var timer: Timer?
    private var networkTask: Task<Void, Never>?
    private var nextPoll = Date.distantPast
    private var nextLocationRequest = Date.distantPast
    private var pendingStart = false
    private var askedAlways = false
    private var seen: [String: Double] = [:]
    private var notifiedIssue: String?

    override init() {
        super.init()
        let defaults = UserDefaults.standard
        radius = defaults.object(forKey: "radius") as? Int ?? 50
        minimumKA = defaults.object(forKey: "minimumKA") as? Double ?? 20
        groundOnly = defaults.object(forKey: "groundOnly") as? Bool ?? true
        token = SecureStore.readToken()
        if token.isEmpty {
            token = SecureStore.bundledToken()
            if !token.isEmpty { _ = SecureStore.saveToken(token) }
        }
        seen = defaults.dictionary(forKey: "notifiedStrikes") as? [String: Double] ?? [:]
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        manager.distanceFilter = 25
        manager.activityType = .otherNavigation
        manager.pausesLocationUpdatesAutomatically = false
        authorization = manager.authorizationStatus
        UNUserNotificationCenter.current().delegate = self
        refreshUsage()
    }

    // Remote inspections are one-shot foreground reads, without location tracking or alerts.
    func inspectZone(latitude: Double, longitude: Double, radius: Int) async throws -> LightningFeed {
        guard !active else {
            throw LightningError.message("Arrête la chasse avant de tester une autre zone.", 60)
        }
        guard token.count >= 32 else {
            throw LightningError.message("Configure le code d’accès personnel dans Réglages.", 60)
        }
        refreshUsage()
        guard todayRequests < 120, monthRequests < 1000 else {
            throw LightningError.message("Limite locale de consultations atteinte.", 900)
        }
        guard Date() >= nextPoll else {
            throw LightningError.message("Attends une minute entre deux consultations.", max(1, Int(nextPoll.timeIntervalSinceNow.rounded(.up))))
        }
        nextPoll = Date().addingTimeInterval(60)
        countRequest()
        do {
            return try await APIClient(endpoint: endpoint, token: token).load(
                latitude: latitude, longitude: longitude, radius: radius, timestamp: Date())
        } catch {
            nextPoll = Date().addingTimeInterval(Double(max(60, (error as? LightningError)?.retry ?? 120)))
            throw error
        }
    }

    func saveAccess() {
        token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        problem = SecureStore.saveToken(token) ? nil : "Impossible d’enregistrer le code dans le trousseau."
    }

    func start() async {
        guard !active else { return }
        guard token.count >= 32 else { problem = "Le code d’accès personnel doit être configuré."; return }
        saveAccess()
        guard CLLocationManager.locationServicesEnabled() else {
            problem = "Active la localisation de l’iPhone dans Réglages."; return
        }
        do {
            let allowed = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            guard allowed else { problem = "Autorise les notifications de KFS Foudre dans Réglages."; return }
        } catch { problem = "Les notifications n’ont pas pu être activées."; return }
        pendingStart = true
        continueAuthorization()
    }

    private func continueAuthorization() {
        authorization = manager.authorizationStatus
        switch authorization {
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse:
            if !askedAlways { askedAlways = true; manager.requestAlwaysAuthorization() }
            problem = "Dans Réglages → KFS Foudre → Position, choisis Toujours pour les déplacements écran verrouillé."
        case .authorizedAlways:
            if pendingStart { beginSession() }
        case .denied, .restricted:
            problem = "L’accès à la position est désactivé. Choisis Toujours dans Réglages."
        @unknown default:
            problem = "Vérifie l’autorisation de localisation dans Réglages."
        }
    }

    private func beginSession() {
        pendingStart = false
        refreshUsage()
        guard todayRequests < 120, monthRequests < 1000 else {
            problem = "Limite de consultations atteinte : 120 par jour ou 1 000 par mois."; return
        }
        active = true
        problem = nil
        notifiedIssue = nil
        status = "Recherche d’une position GPS récente…"
        expiresAt = Date().addingTimeInterval(2 * 3600)
        strikes = []
        lastRefresh = nil
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        manager.startUpdatingLocation()
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    func stop() {
        active = false
        pendingStart = false
        timer?.invalidate(); timer = nil
        networkTask?.cancel(); networkTask = nil
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
        expiresAt = nil
        status = "Surveillance arrêtée"
    }

    func foreground() {
        authorization = manager.authorizationStatus
        if pendingStart { continueAuthorization() }
        if active { tick() }
    }

    private func tick() {
        guard active else { return }
        if let end = expiresAt, Date() >= end {
            stop()
            Task { await issueNotification(title: "Chasse terminée", body: "La séance de deux heures est terminée. Ouvre KFS Foudre pour en démarrer une autre.") }
            return
        }
        guard manager.authorizationStatus == .authorizedAlways else {
            stop(); problem = "L’autorisation Toujours est nécessaire pour cette surveillance."; return
        }
        if location == nil || Date().timeIntervalSince(location!.timestamp) > 45 {
            status = "En attente d’un GPS récent — détection suspendue"
            if Date() >= nextLocationRequest {
                nextLocationRequest = Date().addingTimeInterval(30)
                manager.requestLocation()
            }
            return
        }
        pollIfDue()
    }

    private func pollIfDue() {
        guard active, networkTask == nil, Date() >= nextPoll,
              let fix = location, fix.horizontalAccuracy >= 0, fix.horizontalAccuracy <= 500,
              abs(Date().timeIntervalSince(fix.timestamp)) <= 45 else { return }
        refreshUsage()
        guard todayRequests < 120, monthRequests < 1000 else {
            stop(); problem = "Limite locale de consultations atteinte."; return
        }
        nextPoll = Date().addingTimeInterval(60)
        countRequest()
        let client = APIClient(endpoint: endpoint, token: token)
        let selectedRadius = radius
        let backgroundID = UIApplication.shared.beginBackgroundTask(withName: "Actualisation foudre") { [weak self] in
            Task { @MainActor in self?.networkTask?.cancel() }
        }
        networkTask = Task { [weak self] in
            guard let self else { return }
            defer {
                if backgroundID != .invalid { UIApplication.shared.endBackgroundTask(backgroundID) }
                self.networkTask = nil
            }
            do {
                let feed = try await client.load(latitude: fix.coordinate.latitude,
                    longitude: fix.coordinate.longitude, radius: selectedRadius, timestamp: fix.timestamp)
                guard !Task.isCancelled, self.active else { return }
                self.strikes = feed.strikes
                self.lastRefresh = Date(timeIntervalSince1970: feed.collectedAt)
                self.nextPoll = Date().addingTimeInterval(Double(max(60, feed.pollAfterSeconds)))
                self.problem = feed.partial ? "Liste source limitée : décharges potentiellement manquantes." : nil
                self.status = feed.strikes.isEmpty ? feed.note : "\(feed.strikes.count) décharge(s) fournies sur cinq minutes"
                await self.notifyNew(feed.strikes)
            } catch is CancellationError {
                if self.active { self.problem = "Actualisation interrompue ; reprise au prochain GPS." }
            } catch {
                guard self.active else { return }
                let retry = (error as? LightningError)?.retry ?? 120
                self.nextPoll = Date().addingTimeInterval(Double(max(60, retry)))
                self.problem = error.localizedDescription
                self.status = "Détection indisponible — nouvelle tentative prévue"
            }
        }
    }

    private func notifyNew(_ strikes: [LightningStrike]) async {
        let now = Date()
        seen = seen.filter { now.timeIntervalSince1970 - $0.value < 86400 }
        let policy = AlertPolicy(radiusKm: Double(radius), minimumKA: minimumKA, groundOnly: groundOnly)
        let candidates = policy.candidates(strikes, seen: Set(seen.keys), now: now)
        guard let strongest = candidates.first else { return }
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            problem = "Notifications désactivées dans Réglages."; return
        }
        let content = UNMutableNotificationContent()
        content.title = "⚡ \(strongest.currentLabel) à \(String(format: "%.1f", strongest.distanceKm)) km"
        let time = Date(timeIntervalSince1970: strongest.timestamp).formatted(date: .omitted, time: .standard)
        content.body = "\(strongest.typeLabel) · \(time)" + (candidates.count > 1 ? " · \(candidates.count - 1) autre(s) décharge(s) au-dessus du seuil" : "")
        content.sound = .default
        do {
            try await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "strike-" + strongest.id,
                content: content, trigger: nil))
            for strike in candidates { seen[strike.id] = strike.timestamp }
            UserDefaults.standard.set(seen, forKey: "notifiedStrikes")
        } catch { problem = "L’alerte n’a pas pu être affichée." }
    }

    func testNotification() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
        await issueNotification(title: "Test KFS Foudre", body: "Notification de test uniquement. Aucune décharge réelle.")
    }

    private func issueNotification(title: String, body: String) async {
        let content = UNMutableNotificationContent()
        content.title = title; content.body = body; content.sound = .default
        try? await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString,
            content: content, trigger: nil))
    }

    private func usageKeys() -> (String, String) {
        let formatter = DateFormatter(); formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.dateFormat = "yyyy-MM-dd"
        let day = formatter.string(from: Date())
        return ("queries-day-" + day, "queries-month-" + String(day.prefix(7)))
    }
    private func refreshUsage() {
        let keys = usageKeys()
        todayRequests = UserDefaults.standard.integer(forKey: keys.0)
        monthRequests = UserDefaults.standard.integer(forKey: keys.1)
    }
    private func countRequest() {
        let keys = usageKeys(); todayRequests += 1; monthRequests += 1
        UserDefaults.standard.set(todayRequests, forKey: keys.0)
        UserDefaults.standard.set(monthRequests, forKey: keys.1)
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            self.authorization = manager.authorizationStatus
            if self.pendingStart { self.continueAuthorization() }
            if self.active && self.authorization != .authorizedAlways { self.stop() }
        }
    }
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let fix = locations.last, fix.horizontalAccuracy >= 0, fix.horizontalAccuracy <= 500,
              abs(fix.timestamp.timeIntervalSinceNow) <= 45 else { return }
        Task { @MainActor in
            guard self.active else { return }
            self.location = fix
            self.tick()
        }
    }
    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in if self.active { self.status = "GPS indisponible — en attente d’une position récente" } }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }
}
