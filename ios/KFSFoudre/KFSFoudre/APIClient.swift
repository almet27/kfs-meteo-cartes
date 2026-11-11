import Foundation

struct APIProblem: Decodable { let error: String; let retryAfterSeconds: Int? }
enum LightningError: LocalizedError {
    case message(String, Int)
    var errorDescription: String? { if case let .message(text, _) = self { return text }; return nil }
    var retry: Int { if case let .message(_, retry) = self { return retry }; return 120 }
}

struct APIClient {
    let endpoint: URL
    let token: String

    func load(latitude: Double, longitude: Double, radius: Int, timestamp: Date) async throws -> LightningFeed {
        guard endpoint.scheme == "https", endpoint.host == "kfs-meteo-ia.alain-leprevost.workers.dev",
              endpoint.path == "/mobile/v1/lightning" else {
            throw LightningError.message("Adresse du service personnel invalide.", 300)
        }
        var request = URLRequest(url: endpoint, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "latitude": latitude, "longitude": longitude,
            "radiusKm": radius, "positionTimestamp": timestamp.timeIntervalSince1970
        ])
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        configuration.waitsForConnectivity = false
        let session = URLSession(configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw LightningError.message("Réponse réseau invalide.", 120)
        }
        guard http.statusCode == 200 else {
            let error = try? JSONDecoder().decode(APIProblem.self, from: data)
            throw LightningError.message(error?.error ?? "Service indisponible (\(http.statusCode)).",
                                         error?.retryAfterSeconds ?? 120)
        }
        let feed = try JSONDecoder().decode(LightningFeed.self, from: data)
        guard feed.schema == 1, feed.windowSeconds == 300,
              abs(Date().timeIntervalSince1970 - feed.collectedAt) <= 180 else {
            throw LightningError.message("Données trop anciennes ou format inattendu.", 120)
        }
        return feed
    }
}

private final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
