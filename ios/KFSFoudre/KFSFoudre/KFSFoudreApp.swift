import SwiftUI

@main
struct KFSFoudreApp: App {
    @StateObject private var monitor = HuntMonitor()
    @Environment(\.scenePhase) private var phase
    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(monitor)
                .preferredColorScheme(.dark)
                .onChange(of: phase) { _, value in if value == .active { monitor.foreground() } }
        }
    }
}
