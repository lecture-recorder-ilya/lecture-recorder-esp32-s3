import Foundation

struct LectureNote: Decodable, Identifiable {
    let file: String
    let report: Report
    var lesson: Lesson?
    struct Lesson: Decodable { var subject: String?; var teacher: String?; var date: String? }
    var id: String { file }
    enum CodingKeys: String, CodingKey { case file, report, lesson }

    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        file = try fields.decode(String.self, forKey: .file)
        report = try fields.decode(Report.self, forKey: .report)
        lesson = try? fields.decode(Lesson.self, forKey: .lesson)
    }
    struct Report: Decodable {
        var subject: String?
        var topic: String?
        var overview: String?
        var summary: [String]?
        var segments: [Segment]?
        var summary_evidence: [Citation]?
        var homework: [Citation]?
        var summary_method: String?

        enum CodingKeys: String, CodingKey {
            case subject, topic, overview, summary, segments, summary_evidence, homework, summary_method
        }

        init(from decoder: Decoder) throws {
            let fields = try decoder.container(keyedBy: CodingKeys.self)
            subject = try fields.decodeIfPresent(String.self, forKey: .subject)
            topic = try fields.decodeIfPresent(String.self, forKey: .topic)
            overview = try fields.decodeIfPresent(String.self, forKey: .overview)
            summary = try fields.decodeIfPresent([String].self, forKey: .summary)
            segments = try fields.decodeIfPresent([Segment].self, forKey: .segments)
            summary_evidence = try? fields.decode([Citation].self, forKey: .summary_evidence)
            homework = try? fields.decode([Citation].self, forKey: .homework)
            summary_method = try? fields.decode(String.self, forKey: .summary_method)
        }

        func sourceTime(_ citation: Citation?) -> Double? {
            guard let citation, citation.source_status == "confirmed", let quote = citation.quote,
                  let id = citation.segment_id, let segments, segments.indices.contains(id) else { return nil }
            let source = segments[id]
            guard source.start == citation.start, source.end == citation.end, source.text == quote,
                  source.needs_review != true else { return nil }
            return citation.start
        }
    }
    struct Citation: Decodable {
        var quote: String?
        var task: String?
        var source_status: String?
        var segment_id: Int?
        var start: Double?
        var end: Double?
    }
    struct Segment: Decodable {
        var start: Double?
        var end: Double?
        var text: String
        var needs_review: Bool?
    }
}

enum LibraryLocation: Hashable {
    case segment(Int), overview, summary(Int), homework(Int)
    var materialTab: Int {
        if case .segment = self { return 0 }
        return 1
    }
}

struct LibraryMatch {
    let text: String
    let location: LibraryLocation
}

struct LibraryItem: Identifiable {
    let id: String
    let title: String
    let info: String
    let audio: URL?
    let note: LectureNote?
    private let heading: String
    private let lines: [(LibraryMatch, String)]

    private static let ru = Locale(identifier: "ru_RU")
    private static let fileDate: DateFormatter = {
        let date = DateFormatter()
        date.locale = Locale(identifier: "en_US_POSIX")
        date.timeZone = TimeZone(identifier: "Europe/Moscow")
        date.dateFormat = "yyyy-MM-dd-HH-mm-ss"
        return date
    }()
    private static let displayDate: DateFormatter = {
        let date = DateFormatter()
        date.locale = ru
        date.timeZone = TimeZone(identifier: "Europe/Moscow")
        date.dateFormat = "d MMMM yyyy, HH:mm"
        return date
    }()

    private static func folded(_ value: String) -> String {
        value.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive], locale: ru)
            .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    static func terms(_ query: String) -> [String] {
        folded(query).split(separator: " ").map(String.init)
    }

    init(id: String, audio: URL?, note: LectureNote?, original: String?) {
        self.id = id
        self.audio = audio
        self.note = note
        let topic = note?.report.topic?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let subject = [note?.lesson?.subject, note?.report.subject].compactMap { $0 }.first { !$0.isEmpty } ?? ""
        let source = original.map { URL(fileURLWithPath: $0).deletingPathExtension().lastPathComponent } ?? ""
        let rawDate = id.hasPrefix("lecture-") ? String(id.dropFirst(8).prefix(19)) : ""
        let date = Self.fileDate.date(from: rawDate).map(Self.displayDate.string(from:)) ?? ""
        title = [topic == "Расшифровка записи" ? "" : topic, subject, source,
                 date.isEmpty ? "" : "Запись · " + date].first { !$0.isEmpty } ?? id
        info = [subject == title ? "" : subject, note?.lesson?.teacher ?? "", title == "Запись · " + date ? "" : date]
            .filter { !$0.isEmpty }.joined(separator: " · ")
        heading = Self.folded([title, info, date, original ?? "", id, note?.lesson?.date ?? ""].joined(separator: " "))
        var matches = (note?.report.segments ?? []).enumerated().map {
            LibraryMatch(text: $0.element.text, location: .segment($0.offset))
        }
        if let overview = note?.report.overview, !overview.isEmpty {
            matches.append(LibraryMatch(text: overview, location: .overview))
        }
        matches += (note?.report.summary ?? []).enumerated().map { LibraryMatch(text: $0.element, location: .summary($0.offset)) }
        for (index, task) in (note?.report.homework ?? []).enumerated() {
            if let text = task.task ?? task.quote { matches.append(LibraryMatch(text: text, location: .homework(index))) }
        }
        lines = matches.map { ($0, Self.folded($0.text)) }
    }

    func result(for terms: [String]) -> LibraryResult? {
        let remaining = terms.filter { !heading.contains($0) }
        if remaining.isEmpty { return LibraryResult(item: self, match: nil) }
        guard let found = lines.first(where: { pair in remaining.allSatisfy { pair.1.contains($0) } }) else { return nil }
        return LibraryResult(item: self, match: found.0)
    }

    static func list(_ audio: [URL], notes: [LectureNote], previous: [LibraryItem] = [], changedNotes: Set<String> = [], original: (String) -> String?) -> [LibraryItem] {
        var files: [String: URL] = [:]
        for url in audio { files[url.lastPathComponent] = url }
        var documents: [String: LectureNote] = [:]
        for note in notes { documents[note.file] = note }
        let cached = Dictionary(uniqueKeysWithValues: previous.map { ($0.id, $0) })
        return Set(files.keys).union(documents.keys).sorted(by: >).map { name in
            if let item = cached[name], item.audio == files[name], !changedNotes.contains(name) { return item }
            return LibraryItem(id: name, audio: files[name], note: documents[name], original: original(name))
        }
    }
}

struct LibraryResult: Identifiable {
    let item: LibraryItem
    let match: LibraryMatch?
    var id: String { item.id }
}
