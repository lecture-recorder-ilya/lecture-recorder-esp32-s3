import Combine
import Foundation

struct AudioBookmark: Codable, Identifiable, Equatable {
    let id: UUID
    let name: String
    let time: Double
}

@MainActor final class ListeningLibrary: ObservableObject {
    static let rates: [Float] = [0.75, 1, 1.25, 1.5, 1.75, 2]
    @Published private(set) var favorites: Set<String>
    @Published private(set) var rate: Float
    @Published private(set) var bookmarkRevision = 0
    private let defaults: UserDefaults
    private var bookmarksByFile: [String: [AudioBookmark]] = [:]
    private let prefix = "clipmic.listen."

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        favorites = Set(defaults.stringArray(forKey: prefix + "favorites") ?? [])
        let saved = defaults.float(forKey: prefix + "rate")
        rate = Self.rates.contains(saved) ? saved : 1
    }

    func toggleFavorite(_ file: String) {
        if favorites.contains(file) { favorites.remove(file) } else { favorites.insert(file) }
        defaults.set(favorites.sorted(), forKey: prefix + "favorites")
    }

    func setRate(_ choice: Float) {
        guard Self.rates.contains(choice) else { return }
        rate = choice
        defaults.set(choice, forKey: prefix + "rate")
    }

    func position(_ file: String) -> Double {
        let value = defaults.double(forKey: prefix + "time." + file)
        return value.isFinite && value >= 0 ? value : 0
    }

    func savePosition(_ time: Double, for file: String) {
        guard time.isFinite, time >= 0 else { return }
        defaults.set(time, forKey: prefix + "time." + file)
    }

    func bookmarks(_ file: String) -> [AudioBookmark] {
        if let cached = bookmarksByFile[file] { return cached }
        let stored = defaults.data(forKey: prefix + "marks." + file)
        let values = stored.flatMap { try? JSONDecoder().decode([AudioBookmark].self, from: $0) } ?? []
        bookmarksByFile[file] = values
        return values
    }

    func addBookmark(_ file: String, name: String, at time: Double) {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, time.isFinite, time >= 0 else { return }
        var values = bookmarks(file)
        values.append(AudioBookmark(id: UUID(), name: String(clean.prefix(160)), time: time))
        persist(values.sorted { $0.time < $1.time }, for: file)
    }

    func removeBookmark(_ id: UUID, from file: String) {
        persist(bookmarks(file).filter { $0.id != id }, for: file)
    }

    private func persist(_ values: [AudioBookmark], for file: String) {
        guard let data = try? JSONEncoder().encode(values) else { return }
        defaults.set(data, forKey: prefix + "marks." + file)
        bookmarksByFile[file] = values
        bookmarkRevision += 1
    }
}
