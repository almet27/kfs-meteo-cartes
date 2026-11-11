import SwiftUI
import MapKit
import CoreLocation

struct ContentView: View {
    @EnvironmentObject var monitor: HuntMonitor
    @State private var settings = false
    @State private var remoteTest = false
    private let accent = Color(red: 0.99, green: 0.75, blue: 0.25)
    var body: some View {
        NavigationStack {
            TimelineView(.periodic(from: Date(), by: 15)) { context in
            let visible = monitor.location.map { fix in
                monitor.archive.gps.visible(minutes: monitor.displayMinutes,
                    center: HistoryZone(latitude: fix.coordinate.latitude, longitude: fix.coordinate.longitude, radius: monitor.radius), now: context.date)
            } ?? []
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    HStack {
                        Image(systemName: "bolt.fill").font(.largeTitle).foregroundStyle(accent)
                        VStack(alignment: .leading) {
                            Text("KFS FOUDRE").font(.title2.bold()).tracking(2)
                            Text("Ton suivi électrique en déplacement").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Circle().fill(monitor.active ? .green : .gray).frame(width: 10, height: 10)
                    }
                    Map {
                        if let fix = monitor.location {
                            Annotation("Ma position", coordinate: fix.coordinate) {
                                Circle().fill(.white).frame(width: 13, height: 13)
                                    .overlay(Circle().stroke(.blue, lineWidth: 3))
                            }
                            MapCircle(center: fix.coordinate, radius: Double(monitor.radius) * 1000)
                                .foregroundStyle(accent.opacity(0.05)).stroke(accent.opacity(0.5), lineWidth: 1)
                        }
                        ForEach(Array(visible.prefix(5000))) { strike in
                            Annotation(strike.currentLabel, coordinate: CLLocationCoordinate2D(latitude: strike.latitude, longitude: strike.longitude)) {
                                Image(systemName: strike.type == "cg" ? "bolt.fill" : "cloud.bolt.fill")
                                    .foregroundStyle((strike.peakCurrentKA ?? 0) > 0 ? accent : .cyan)
                                    .padding(6).background(.ultraThinMaterial, in: Circle())
                            }
                        }
                    }
                    .mapStyle(.standard(elevation: .flat))
                    .frame(height: 260).clipShape(RoundedRectangle(cornerRadius: 24))
                    if visible.count > 5000 { Text("Carte : 5 000 décharges les plus récentes ; liste complète ci-dessous.").font(.caption).foregroundStyle(.orange) }
                    HistoryControls(history: monitor.archive.gps, minutes: $monitor.displayMinutes, moving: true, now: context.date)
                    HStack(spacing: 12) {
                        metric("RAYON", "\(monitor.radius) km")
                        metric("SEUIL", "≥ \(Int(monitor.minimumKA)) kA")
                        metric("DÉCHARGES", "\(visible.count)")
                    }
                    VStack(alignment: .leading, spacing: 7) {
                        Label(monitor.active ? "Surveillance en cours" : "Surveillance arrêtée",
                              systemImage: monitor.active ? "location.fill" : "pause.circle")
                            .font(.headline).foregroundStyle(monitor.active ? .green : .secondary)
                        Text(monitor.status).font(.subheadline)
                        if let date = monitor.lastRefresh {
                            Text("Source consultée à \(date.formatted(date: .omitted, time: .standard))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if let end = monitor.expiresAt {
                            Text("Fin de séance : \(end.formatted(date: .omitted, time: .shortened))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if let issue = monitor.historyIssue {
                        Text(issue).font(.caption).foregroundStyle(.orange)
                    }
                    if let problem = monitor.problem {
                        Label(problem, systemImage: "exclamationmark.circle").font(.footnote).foregroundStyle(.orange)
                    }
                    Button {
                        if monitor.active { monitor.stop() } else { Task { await monitor.start() } }
                    } label: {
                        Label(monitor.active ? "Arrêter la chasse" : "Démarrer la chasse",
                              systemImage: monitor.active ? "stop.fill" : "location.fill")
                            .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 11)
                    }
                    .buttonStyle(.borderedProminent).tint(monitor.active ? .red : accent)
                    .foregroundStyle(monitor.active ? .white : .black)
                    Button { remoteTest = true } label: {
                        Label("Tester une zone d’Europe", systemImage: "globe.europe.africa.fill")
                    }
                    .disabled(monitor.active)
                    if monitor.active {
                        Text("Arrête la chasse pour consulter une zone à distance.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Text("Position suivie pendant la séance, y compris écran verrouillé avec l’autorisation Toujours. Consultations au mieux toutes les minutes selon GPS, réseau et fonctionnement d’iOS.")
                        .font(.caption).foregroundStyle(.secondary)
                    if !visible.isEmpty {
                        Text("Décharges conservées · \(monitor.displayMinutes) min").font(.headline)
                        ForEach(visible) { strike in
                            HStack {
                                Image(systemName: "bolt.fill").foregroundStyle((strike.peakCurrentKA ?? 0) > 0 ? accent : .cyan)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(strike.currentLabel).font(.title3.bold().monospacedDigit())
                                    Text(strike.typeLabel).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                VStack(alignment: .trailing) {
                                    Text(String(format: "%.1f km", strike.distanceKm)).font(.headline.monospacedDigit())
                                    Text(Date(timeIntervalSince1970: strike.timestamp).formatted(date: .omitted, time: .standard))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }.padding().background(.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 15))
                        }
                    }
                    Text("Source : Vaisala Xweather · historique local des décharges reçues, jusqu’à une heure. Les kA sont le courant de crête estimé par le réseau, pas une puissance. Aucune donnée reçue ne prouve pas l’absence d’orage.")
                        .font(.caption2).foregroundStyle(.secondary)
                    Link("Vaisala Xweather", destination: URL(string: "https://www.xweather.com/")!).font(.caption)
                }.padding(20)
            }
            .background(Color(red: 0.035, green: 0.065, blue: 0.10))
            }
            .toolbar { ToolbarItem(placement: .topBarTrailing) {
                Button { settings = true } label: { Image(systemName: "slider.horizontal.3") }
            }}
            .sheet(isPresented: $settings) { SettingsView().environmentObject(monitor) }
            .sheet(isPresented: $remoteTest) { RemoteTestView().environmentObject(monitor) }
        }
    }
    private func metric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.system(size: 9, weight: .bold)).tracking(1).foregroundStyle(.secondary)
            Text(value).font(.headline.monospacedDigit())
        }.frame(maxWidth: .infinity, alignment: .leading).padding(13)
            .background(.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 15))
    }
}

struct SettingsView: View {
    @EnvironmentObject var monitor: HuntMonitor
    @Environment(\.dismiss) var dismiss
    var body: some View {
        NavigationStack {
            Form {
                Section("Autour de moi") {
                    Picker("Rayon", selection: $monitor.radius) {
                        ForEach([10, 30, 50, 100], id: \.self) { Text("\($0) km").tag($0) }
                    }
                    Stepper("Seuil : \(Int(monitor.minimumKA)) kA", value: $monitor.minimumKA, in: 0...200, step: 5)
                    Toggle("Alertes nuage-sol uniquement", isOn: $monitor.groundOnly)
                    Text("Le seuil s’applique à la valeur absolue : −50 et +50 kA dépassent tous deux 50 kA.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("iPhone") {
                    Button("Tester une notification") { Task { await monitor.testNotification() } }
                    Button("Ouvrir les autorisations iPhone") {
                        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                    }
                    Text("Autorise les notifications et la position Toujours. Garde l’app ouverte en arrière-plan pendant la chasse ; ne la force pas à quitter.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Consommation maîtrisée") {
                    Text("Aujourd’hui : \(monitor.todayRequests) / 120 consultations")
                    Text("Ce mois : \(monitor.monthRequests) / 1 000 consultations")
                    Text("Une séance dure au maximum 2 heures. Ces plafonds locaux limitent les appels ; ils ne garantissent pas le quota restant du compte Xweather partagé avec Discord.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Historique sur cet iPhone") {
                    Text("Les décharges reçues sont conservées jusqu’à une heure avec leurs kA. La collecte commence lors des consultations ; une interruption réseau peut laisser un trou.")
                        .font(.caption)
                    Button("Effacer l’historique", role: .destructive) { monitor.clearHistory() }
                }
                Section("Accès personnel") {
                    SecureField("Code personnel", text: $monitor.token).textContentType(.password)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                    Button("Enregistrer le code") { monitor.saveAccess() }
                    Text("Le code est conservé dans le trousseau de cet iPhone. La position n’est envoyée au service météo que pendant une séance ; aucun trajet n’est enregistré.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.navigationTitle("Réglages")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Fermer") { dismiss() } } }
        }
    }
}


struct HistoryControls: View {
    let history: LightningHistory
    @Binding var minutes: Int
    let moving: Bool
    let now: Date
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Historique affiché", selection: $minutes) {
                Text("5 min").tag(5)
                Text("30 min").tag(30)
                Text("1 h").tag(60)
            }.pickerStyle(.segmented)
            let coverage = history.coverage(minutes: minutes, now: now)
            Text("Fenêtres reçues : \(Int(coverage.coveredSeconds / 60)) / \(minutes) min")
                .font(.caption.bold())
            if coverage.coveredSeconds == 0 {
                Text("En attente d’une première consultation réussie. Aucun historique antérieur n’est récupéré.")
                    .font(.caption).foregroundStyle(.secondary)
            } else if coverage.missingSeconds > 60 {
                Text("Historique en construction ou collecte interrompue : environ \(Int(ceil(coverage.missingSeconds / 60))) min non couvertes.")
                    .font(.caption).foregroundStyle(.orange)
            }
            if coverage.segments > 1 {
                Text("Des interruptions séparent les fenêtres reçues.").font(.caption).foregroundStyle(.orange)
            }
            if coverage.partial {
                Text("Historique partiel : une réponse source ou la capacité de stockage a été limitée.")
                    .font(.caption).foregroundStyle(.orange)
            }
            Text(moving ? "Couverture temporelle des secteurs consultés. En déplacement ou après un changement de rayon, les secteurs précédents ne couvrent pas forcément toute la zone actuelle." : "Couverture temporelle des réponses Xweather sur cette zone ; elle ne garantit pas la détection de tous les éclairs.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }
}

struct StrikeHistoryRow: View {
    let strike: LightningStrike
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(strike.currentLabel).bold()
                Text(strike.typeLabel).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing) {
                Text(String(format: "%.1f km", strike.distanceKm))
                Text(Date(timeIntervalSince1970: strike.timestamp).formatted(date: .omitted, time: .standard))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct RemoteHistoryResult: View {
    let history: LightningHistory
    let zone: HistoryZone
    let name: String
    @Binding var minutes: Int
    let now: Date
    private var center: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: zone.latitude, longitude: zone.longitude)
    }
    var body: some View {
        let events = history.visible(minutes: minutes, center: zone, now: now)
        Section(name) {
            HistoryControls(history: history, minutes: $minutes, moving: false, now: now)
            historyMap(events)
            if events.count > 5000 { Text("Carte : 5 000 décharges les plus récentes ; liste complète ci-dessous.").font(.caption).foregroundStyle(.orange) }
            Text("\(events.count) décharge(s) conservée(s) · \(minutes) min")
            if let end = history.windows.map(\.end).max() {
                Text("Dernière réception : \(Date(timeIntervalSince1970: end).formatted(date: .omitted, time: .standard))")
                    .font(.caption)
            }
            if events.isEmpty {
                Text("Aucune décharge reçue et conservée dans cette fenêtre. Cela ne prouve pas l’absence d’orage.")
                    .font(.footnote)
            }
            ForEach(events) { StrikeHistoryRow(strike: $0) }
        }
    }
    private func historyMap(_ events: [LightningStrike]) -> some View {
        Map {
            Annotation("Centre de l’essai", coordinate: center) {
                Image(systemName: "scope").foregroundStyle(.orange)
            }
            MapCircle(center: center, radius: Double(zone.radius) * 1000)
                .foregroundStyle(.orange.opacity(0.05)).stroke(.orange.opacity(0.5), lineWidth: 1)
            ForEach(Array(events.prefix(5000))) { strike in
                Annotation(strike.currentLabel, coordinate: CLLocationCoordinate2D(latitude: strike.latitude, longitude: strike.longitude)) {
                    Image(systemName: strike.type == "cg" ? "bolt.fill" : "cloud.bolt.fill")
                        .foregroundStyle((strike.peakCurrentKA ?? 0) > 0 ? .orange : .cyan)
                        .padding(6).background(.ultraThinMaterial, in: Circle())
                }
            }
        }.frame(height: 260).id(zone.key)
    }
}

struct RemoteTestView: View {
    @EnvironmentObject var monitor: HuntMonitor
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var phase
    @State private var city = ""
    @State private var latitude = ""
    @State private var longitude = ""
    @State private var radius = 100
    @State private var minutes = 30
    @State private var busy = false
    @State private var problem: String?
    @State private var collecting = false
    @State private var nextTry = Date.distantPast
    private let geocoder = CLGeocoder()

    var body: some View {
        NavigationStack {
            TimelineView(.periodic(from: Date(), by: 15)) { context in
                Form {
                    querySection
                    if let problem { Section { Text(problem).foregroundStyle(.orange) } }
                    if let issue = monitor.historyIssue { Section { Text(issue).foregroundStyle(.orange) } }
                    if let zone = monitor.archive.remoteZone {
                        collectionSection(zone)
                        RemoteHistoryResult(history: monitor.archive.remote, zone: zone,
                            name: monitor.archive.remoteName, minutes: $minutes, now: context.date)
                    }
                    Section {
                        Text("Source : Vaisala Xweather. Les kA sont un courant de crête estimé. Les données reçues sont conservées localement une heure, sans récupération des impacts antérieurs à la collecte.")
                            .font(.caption)
                    }
                }
            }
            .navigationTitle("Tester une zone")
            .toolbar { ToolbarItem(placement: .confirmationAction) {
                Button("Fermer") { collecting = false; dismiss() }.disabled(busy)
            }}
            .interactiveDismissDisabled(busy)
            .onChange(of: phase) { _, value in if value != .active { collecting = false } }
            .onDisappear { collecting = false }
            .task(id: collecting) {
                guard collecting else { return }
                while !Task.isCancelled && collecting {
                    let wait = max(1, nextTry.timeIntervalSinceNow)
                    do { try await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000)) }
                    catch { return }
                    guard !Task.isCancelled, collecting, phase == .active,
                          let zone = monitor.archive.remoteZone else { return }
                    await fetchZone(zone, name: monitor.archive.remoteName)
                }
            }
        }
    }

    private var querySection: some View {
        Section("Essai à distance · Europe") {
            Text("Choisis une zone. Les consultations alimentent son historique, sans modifier ton GPS et sans déclencher d’alertes. Changer de zone ou de rayon démarre un nouvel historique d’essai.")
                .font(.footnote)
            Group {
                TextField("Ville et pays, ex. Barga, Italie", text: $city)
                Text("Ou des coordonnées, prioritaires sur la ville.").font(.caption).foregroundStyle(.secondary)
                TextField("Latitude", text: $latitude).keyboardType(.numbersAndPunctuation)
                TextField("Longitude", text: $longitude).keyboardType(.numbersAndPunctuation)
                Picker("Rayon", selection: $radius) {
                    ForEach([10, 30, 50, 100], id: \.self) { Text("\($0) km").tag($0) }
                }
                Button { Task { await inspect() } } label: {
                    if busy { ProgressView("Consultation…") }
                    else { Label("Consulter cette zone", systemImage: "bolt.fill") }
                }
            }.disabled(busy || collecting)
            Text("Une consultation au maximum par minute, partagée avec la chasse et ses plafonds.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func collectionSection(_ zone: HistoryZone) -> some View {
        Section("Collecte de la zone affichée") {
            Button {
                collecting.toggle()
                if collecting { nextTry = max(nextTry, Date()) }
            } label: {
                Label(collecting ? "Arrêter la collecte" : "Collecter chaque minute",
                    systemImage: collecting ? "stop.circle.fill" : "play.circle.fill")
            }.disabled(busy)
            Text(collecting ? "Collecte automatique active pour \(monitor.archive.remoteName)." : "Collecte automatique arrêtée.")
                .font(.caption)
            Text("Garde cet écran ouvert et l’iPhone déverrouillé. Fermer l’écran ou mettre l’app en arrière-plan arrête cette collecte distante. Les impacts déjà reçus restent consultables jusqu’à une heure.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    @MainActor private func fetchZone(_ zone: HistoryZone, name: String) async {
        guard !busy else { return }
        busy = true; problem = nil
        defer { busy = false }
        do {
            let feed = try await monitor.inspectZone(latitude: zone.latitude, longitude: zone.longitude, radius: zone.radius, name: name)
            nextTry = Date().addingTimeInterval(Double(max(60, feed.pollAfterSeconds)))
        } catch is CancellationError {
            return
        } catch {
            problem = error.localizedDescription
            nextTry = Date().addingTimeInterval(Double(max(60, (error as? LightningError)?.retry ?? 120)))
            // Avoid a failed request loop after local caps are reached.
            if monitor.todayRequests >= 120 || monitor.monthRequests >= 1000 { collecting = false }
        }
    }

    @MainActor private func inspect() async {
        guard !busy, !collecting else { return }
        guard Date() >= nextTry else {
            problem = "Attends encore \(max(1, Int(nextTry.timeIntervalSinceNow.rounded(.up)))) secondes."; return
        }
        busy = true; problem = nil
        do {
            let center: CLLocationCoordinate2D
            var name: String
            let latText = latitude.trimmingCharacters(in: .whitespacesAndNewlines)
            let lonText = longitude.trimmingCharacters(in: .whitespacesAndNewlines)
            if !latText.isEmpty || !lonText.isEmpty {
                guard let lat = Double(latText.replacingOccurrences(of: ",", with: ".")),
                      let lon = Double(lonText.replacingOccurrences(of: ",", with: ".")) else {
                    throw LightningError.message("Renseigne une latitude et une longitude valides.", 0)
                }
                center = CLLocationCoordinate2D(latitude: lat, longitude: lon)
                name = "\(lat), \(lon)"
            } else {
                let query = city.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !query.isEmpty else { throw LightningError.message("Indique une ville et son pays, ou des coordonnées.", 0) }
                let matches = try await geocoder.geocodeAddressString(query)
                guard let fix = matches.first?.location else { throw LightningError.message("Ville introuvable. Essaie les coordonnées.", 0) }
                center = fix.coordinate
                name = [matches.first?.locality, matches.first?.country].compactMap { $0 }.joined(separator: ", ")
                if name.isEmpty { name = query }
            }
            guard center.latitude.isFinite, center.longitude.isFinite,
                  (30...72).contains(center.latitude), (-25...45).contains(center.longitude) else {
                throw LightningError.message("Choisis une zone européenne (latitude 30 à 72°, longitude −25 à 45°).", 0)
            }
            busy = false
            await fetchZone(HistoryZone(latitude: center.latitude, longitude: center.longitude, radius: radius), name: name)
        } catch {
            busy = false; problem = error.localizedDescription
        }
    }
}
