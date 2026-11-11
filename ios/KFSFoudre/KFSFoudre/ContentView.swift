import SwiftUI
import MapKit

struct ContentView: View {
    @EnvironmentObject var monitor: HuntMonitor
    @State private var settings = false
    private let accent = Color(red: 0.99, green: 0.75, blue: 0.25)
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
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
                        ForEach(monitor.strikes) { strike in
                            Annotation(strike.currentLabel, coordinate: CLLocationCoordinate2D(latitude: strike.latitude, longitude: strike.longitude)) {
                                Image(systemName: strike.type == "cg" ? "bolt.fill" : "cloud.bolt.fill")
                                    .foregroundStyle((strike.peakCurrentKA ?? 0) > 0 ? accent : .cyan)
                                    .padding(6).background(.ultraThinMaterial, in: Circle())
                            }
                        }
                    }
                    .mapStyle(.standard(elevation: .flat))
                    .frame(height: 260).clipShape(RoundedRectangle(cornerRadius: 24))
                    HStack(spacing: 12) {
                        metric("RAYON", "\(monitor.radius) km")
                        metric("SEUIL", "≥ \(Int(monitor.minimumKA)) kA")
                        metric("DÉCHARGES", "\(monitor.strikes.count)")
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
                    Text("Position suivie pendant la séance, y compris écran verrouillé avec l’autorisation Toujours. Consultations au mieux toutes les minutes selon GPS, réseau et fonctionnement d’iOS.")
                        .font(.caption).foregroundStyle(.secondary)
                    if !monitor.strikes.isEmpty {
                        Text("Dernières décharges fournies").font(.headline)
                        ForEach(monitor.strikes) { strike in
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
                    Text("Source : Vaisala Xweather · fenêtre de 5 minutes. Les kA sont le courant de crête estimé par le réseau, pas une puissance. Aucune donnée reçue ne prouve pas l’absence d’orage.")
                        .font(.caption2).foregroundStyle(.secondary)
                    Link("Vaisala Xweather", destination: URL(string: "https://www.xweather.com/")!).font(.caption)
                }.padding(20)
            }
            .background(Color(red: 0.035, green: 0.065, blue: 0.10))
            .toolbar { ToolbarItem(placement: .topBarTrailing) {
                Button { settings = true } label: { Image(systemName: "slider.horizontal.3") }
            }}
            .sheet(isPresented: $settings) { SettingsView().environmentObject(monitor) }
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
