import AVFoundation
import SwiftUI
import UniformTypeIdentifiers

private struct LibraryRoute: Hashable {
    let file: String
    var location: LibraryLocation?
}

struct LibraryScreen: View {
    @ObservedObject var model: PhoneModel
    @Binding var requestedFile: String?
    @State private var path: [LibraryRoute] = []
    @State private var openedReceipt: String?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var query = ""
    @State private var favoritesOnly = false
    @State private var importing = false
    @State private var results: [LibraryResult] = []

    var body: some View {
        NavigationStack(path: $path) {
            List {
                Picker("Записи", selection: $favoritesOnly) {
                    Text("Все").tag(false)
                    Text("Избранное").tag(true)
                }
                .pickerStyle(.segmented).listRowBackground(Color.clear).listRowInsets(EdgeInsets())
                if !model.drafts.isEmpty && query.isEmpty && !favoritesOnly {
                    Section("Незавершённые записи") {
                        ForEach(model.drafts, id: \.path) { file in
                            Button("Восстановить запись") { model.importAudio(file, removeDraft: true) }
                                .disabled(model.busy || model.recording)
                        }
                    }
                }
                if model.busy && !model.starting {
                    ProgressView("Сохраняем запись…").listRowBackground(Color.clear)
                }
                if !model.captureNotice.isEmpty {
                    Text(model.captureNotice).font(.footnote).foregroundStyle(Studio.muted)
                        .listRowBackground(Color.clear)
                }
                if let saved = model.savedItem, openedReceipt != saved.id {
                    Button { path = [LibraryRoute(file: saved.id)] } label: {
                        SavedRecordingRow(title: saved.title)
                    }
                    .buttonStyle(.plain).listRowInsets(EdgeInsets()).listRowBackground(Color.clear)
                }
                if results.isEmpty {
                    Text(!query.isEmpty ? "По запросу ничего не найдено" : (favoritesOnly ? "В избранном пока пусто" : "Пока нет записей"))
                        .foregroundStyle(Studio.muted).listRowBackground(Color.clear)
                } else {
                    ForEach(results) { result in
                        let favorite = model.listening.favorites.contains(result.id)
                        NavigationLink(value: LibraryRoute(file: result.id, location: result.match?.location)) {
                            HStack(spacing: 13) {
                                Image(systemName: result.item.audio == nil ? "doc.text" : "waveform")
                                    .font(.body.weight(.medium)).foregroundStyle(Studio.accent)
                                    .frame(width: 40, height: 44)
                                    .background(Studio.hero, in: RoundedRectangle(cornerRadius: 10))
                                    .accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 5) {
                                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                                        Text(result.item.title).font(.headline).fixedSize(horizontal: false, vertical: true)
                                        if favorite { Image(systemName: "star.fill").font(.caption).foregroundStyle(Studio.accent).accessibilityLabel("В избранном") }
                                    }
                                    if !result.item.info.isEmpty {
                                        Text(result.item.info).font(.footnote).foregroundStyle(Studio.muted)
                                    }
                                    if let match = result.match {
                                        Text(match.text).font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
                                    }
                                }
                            }.padding(.vertical, 7)
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            Button { model.listening.toggleFavorite(result.id) } label: {
                                Label(favorite ? "Убрать" : "В избранное", systemImage: favorite ? "star.slash" : "star")
                            }.tint(Studio.card)
                        }
                        .accessibilityAction(named: favorite ? "Убрать из избранного" : "Добавить в избранное") {
                            model.listening.toggleFavorite(result.id)
                        }
                        .listRowBackground(Studio.panel)
                    }
                }
            }
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Название или фраза")
            .navigationDestination(for: LibraryRoute.self) { route in
                if let item = model.libraryItems.first(where: { $0.id == route.file }) {
                    ReaderScreen(model: model, initial: item, location: route.location)
                } else {
                    Text("Материал больше недоступен").foregroundStyle(Studio.muted)
                }
            }
            .onAppear { filter() }
            .onReceive(model.$libraryItems) { filter(items: $0) }
            .onReceive(model.listening.$favorites) { filter(favorites: $0) }
            .onChange(of: query) { _ in filter() }
            .onChange(of: favoritesOnly) { _ in filter() }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.16), value: favoritesOnly)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.14), value: results.map(\.id))
            .scrollContentBackground(.hidden)
            .navigationTitle("Библиотека")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { importing = true } label: { Label("Загрузить аудио или видео", systemImage: "square.and.arrow.down") }
                        .disabled(model.busy || model.recording)
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) { MiniPlayer(model: model, playback: model.playback) }
            .studioScreen()
            .fileImporter(isPresented: $importing, allowedContentTypes: [.audio, .movie], onCompletion: model.selectImport)
        }
        .onChange(of: path) { routes in
            if let file = routes.last?.file, file == model.savedFile { openedReceipt = file }
        }
        .task(id: requestedFile) {
            guard let file = requestedFile else { return }
            path = [LibraryRoute(file: file)]
            requestedFile = nil
        }
    }

    private func filter(items: [LibraryItem]? = nil, favorites: Set<String>? = nil) {
        let terms = LibraryItem.terms(query)
        let starred = favorites ?? model.listening.favorites
        results = (items ?? model.libraryItems).compactMap {
            favoritesOnly && !starred.contains($0.id) ? nil : $0.result(for: terms)
        }
    }
}

private struct MiniPlayer: View {
    @ObservedObject var model: PhoneModel
    @ObservedObject var playback: LecturePlayback
    var body: some View {
        if let id = playback.file, let item = model.libraryItems.first(where: { $0.id == id }), let file = item.audio {
            HStack {
                NavigationLink(value: LibraryRoute(file: item.id)) {
                    VStack(alignment: .leading) {
                        Text(item.title).font(.subheadline.weight(.semibold)).lineLimit(2)
                        Text(clock(playback.elapsed)).font(.caption.monospacedDigit()).foregroundStyle(Studio.muted)
                    }
                }
                Spacer()
                Button {
                    if playback.playing { playback.pause() } else { model.play(file) }
                } label: { Image(systemName: playback.playing ? "pause.fill" : "play.fill").frame(minWidth: 44, minHeight: 44) }
                    .accessibilityLabel(playback.playing ? "Пауза" : "Продолжить")
                    .disabled(model.recording || model.busy)
            }
            .padding(.horizontal, 20).padding(.vertical, 5)
            .modifier(DeskGlass(radius: 20))
            .padding(.horizontal, 12).padding(.vertical, 4)
        }
    }
}

private struct BookmarkDraft: Identifiable {
    let id = UUID()
    let seconds: Double
}

struct ReaderScreen: View {
    @ObservedObject var model: PhoneModel
    @ObservedObject private var listening: ListeningLibrary
    let initial: LibraryItem
    let location: LibraryLocation?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var textSize
    @State private var tab: Int
    @State private var bookmark: BookmarkDraft?
    @State private var toRemove: AudioBookmark?

    init(model: PhoneModel, initial: LibraryItem, location: LibraryLocation?) {
        self.model = model; self.initial = initial; self.location = location
        _listening = ObservedObject(wrappedValue: model.listening)
        _tab = State(initialValue: initial.note == nil ? 2 : (location?.materialTab ?? 0))
    }
    private var item: LibraryItem { model.libraryItems.first { $0.id == initial.id } ?? initial }

    var body: some View {
        ScrollViewReader { scroll in
            List {
                if let audio = item.audio {
                    PlaybackControls(model: model, playback: model.playback, listening: listening, audio: audio) {
                        bookmark = BookmarkDraft(seconds: $0)
                    }.listRowBackground(Studio.hero)
                    if item.note == nil {
                        if model.transcribingFile == item.id {
                            ProgressView(value: Double(model.transcriptionProgress), total: 100) { Text("Расшифровка · " + String(model.transcriptionProgress) + "%") }
                            Button("Отменить расшифровку") { model.cancelTranscription() }
                        } else if OnDeviceTranscript.supported {
                            Button("Расшифровать на iPhone") { model.transcribe(audio) }
                                .disabled(model.recording || model.busy || model.transcribingFile != nil)
                        } else {
                            Text("На устройстве недоступна русская модель офлайн-распознавания.")
                                .font(.footnote).foregroundStyle(Studio.muted)
                        }
                    }
                } else {
                    Text("Аудиокопии на телефоне нет.").font(.footnote).foregroundStyle(Studio.muted)
                }
                if item.note != nil {
                    materialPicker.listRowBackground(Studio.panel)
                }
                if (tab == 2 || item.note == nil) {
                    Section("Закладки") {
                        let marks = listening.bookmarks(item.id)
                        if marks.isEmpty {
                            Text("Закладок пока нет").font(.subheadline).foregroundStyle(Studio.muted)
                        }
                        ForEach(marks) { mark in
                            HStack {
                                Button {
                                    if let file = item.audio { model.play(file, at: mark.time) }
                                } label: {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Label(clock(mark.time), systemImage: "bookmark.fill").font(.caption.monospacedDigit())
                                        Text(mark.name).foregroundStyle(.primary).multilineTextAlignment(.leading)
                                    }.frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .buttonStyle(.plain).disabled(item.audio == nil || model.recording || model.busy)
                                Button(role: .destructive) { toRemove = mark } label: {
                                    Image(systemName: "trash").frame(minWidth: 44, minHeight: 44)
                                }.buttonStyle(.borderless).accessibilityLabel("Удалить закладку «" + mark.name + "»")
                            }
                        }
                    }.listRowBackground(Studio.panel)
                } else if let note = item.note, tab == 0 {
                    ForEach(Array((note.report.segments ?? []).enumerated()), id: \.offset) { index, segment in
                        quotation(segment.text, at: segment.start, end: segment.end, review: segment.needs_review == true)
                            .id(LibraryLocation.segment(index))
                    }
                } else if let note = item.note {
                    if let overview = note.report.overview, !overview.isEmpty { Text(overview).font(.system(.body, design: .serif)).foregroundStyle(Studio.paperInk).id(LibraryLocation.overview).listRowBackground(Studio.paper) }
                    ForEach(Array((note.report.summary ?? []).enumerated()), id: \.offset) { index, text in
                        let citations = note.report.summary_evidence ?? []
                        quotation(text, at: note.report.sourceTime(citations.indices.contains(index) ? citations[index] : nil)).id(LibraryLocation.summary(index))
                    }
                    if let tasks = note.report.homework, !tasks.isEmpty {
                        Section("Домашнее задание") {
                            ForEach(Array(tasks.enumerated()), id: \.offset) { index, task in
                                if let text = task.task ?? task.quote {
                                    quotation(text, at: note.report.sourceTime(task)).id(LibraryLocation.homework(index))
                                }
                            }
                        }
                    }
                    if note.report.summary?.isEmpty != false && note.report.homework?.isEmpty != false && (note.report.overview ?? "").isEmpty {
                        Text("Конспект пока пуст").foregroundStyle(Studio.muted)
                    }
                }
                if !model.message.isEmpty {
                    Text(model.message).font(.footnote).foregroundStyle(Studio.muted).listRowBackground(Color.clear)
                }
            }
            .task {
                if let location {
                    await Task.yield()
                    scroll.scrollTo(location, anchor: .top)
                }
            }
        }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: tab)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: listening.bookmarkRevision)
        .scrollContentBackground(.hidden)
        .navigationTitle(item.title).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if let url = item.audio {
                    ShareLink(item: url) { Image(systemName: "square.and.arrow.up").accessibilityLabel("Поделиться записью") }
                }
                Button { listening.toggleFavorite(item.id) } label: {
                    Image(systemName: listening.favorites.contains(item.id) ? "star.fill" : "star")
                }.accessibilityLabel(listening.favorites.contains(item.id) ? "Убрать из избранного" : "Добавить в избранное")
            }
        }
        .sheet(item: $bookmark) { draft in
            BookmarkNameForm(time: draft.seconds, number: listening.bookmarks(item.id).count + 1) { name in
                listening.addBookmark(item.id, name: name, at: draft.seconds)
                tab = 2
            }
        }
        .confirmationDialog("Удалить закладку?", isPresented: Binding(get: { toRemove != nil }, set: { if !$0 { toRemove = nil } }), presenting: toRemove) { mark in
            Button("Удалить «" + mark.name + "»", role: .destructive) { listening.removeBookmark(mark.id, from: item.id); toRemove = nil }
        }
        .studioScreen()
    }

    @ViewBuilder private var materialPicker: some View {
        let control = Picker("Материалы", selection: $tab) {
            Text("Текст").tag(0); Text("Конспект").tag(1); Text("Закладки").tag(2)
        }
        if textSize.isAccessibilitySize { control.pickerStyle(.menu) }
        else { control.pickerStyle(.segmented) }
    }

    @ViewBuilder private func quotation(_ text: String, at start: Double?, end: Double? = nil, review: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let start { Label(clock(start), systemImage: "play.circle").font(.caption.monospacedDigit()).foregroundStyle(Studio.paperAccent) }
            Text(text).font(.system(.body, design: .serif)).lineSpacing(3)
                .foregroundStyle(Studio.paperInk).multilineTextAlignment(.leading)
            if review { Label("Проверь по записи", systemImage: "ear").font(.caption).foregroundStyle(Studio.paperWarning) }
        }
        .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 7)
        .modifier(PlayableQuote(action: item.audio.flatMap { audio in start.map { seconds in { model.play(audio, at: seconds) } } },
                                disabled: model.recording || model.busy))
        .listRowBackground(PlaybackPaper(playback: model.playback, file: item.id, start: start, end: end))
    }
}

private struct PlaybackPaper: View {
    @ObservedObject var playback: LecturePlayback
    let file: String
    let start: Double?
    let end: Double?

    var body: some View {
        if playback.playing, playback.file == file, let start, let end,
           start <= playback.elapsed, playback.elapsed < end {
            Studio.paperSelection.overlay(alignment: .leading) {
                Rectangle().fill(Studio.paperAccent).frame(width: 3)
            }
        } else {
            Studio.paper
        }
    }
}

private struct PlayableQuote: ViewModifier {
    let action: (() -> Void)?
    let disabled: Bool
    @ViewBuilder func body(content: Content) -> some View {
        if let action { Button(action: action) { content }.buttonStyle(.plain).disabled(disabled) } else { content }
    }
}

private struct BookmarkNameForm: View {
    @Environment(\.dismiss) private var dismiss
    let time: Double
    let save: (String) -> Void
    @State private var name: String
    init(time: Double, number: Int, save: @escaping (String) -> Void) {
        self.time = time; self.save = save; _name = State(initialValue: "Закладка " + String(number))
    }
    var body: some View {
        NavigationStack {
            Form {
                Section(clock(time)) { TextField("Название закладки", text: $name).accessibilityLabel("Название закладки") }
            }
            .navigationTitle("Новая закладка").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Отмена") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Сохранить") { save(name); dismiss() }.disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }.studioScreen()
        }.presentationDetents([.medium, .large])
    }
}

private struct PlaybackControls: View {
    @ObservedObject var model: PhoneModel
    @ObservedObject var playback: LecturePlayback
    @ObservedObject var listening: ListeningLibrary
    let audio: URL
    let bookmark: (Double) -> Void
    @State private var drag: Double?
    @State private var localDuration = 0.0
    @State private var saved = 0.0
    private var id: String { audio.lastPathComponent }
    private var active: Bool { playback.file == id }
    private var playing: Bool { active && playback.playing }
    private var length: Double { active ? playback.duration : localDuration }
    private var time: Double { drag ?? (active ? playback.elapsed : saved) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if length > 0 {
                Slider(value: Binding(get: { min(length, max(0, time)) }, set: { drag = $0 }),
                       in: 0...length, onEditingChanged: { editing in
                    if !editing, let position = drag { seek(position); drag = nil }
                })
                .accessibilityLabel("Позиция воспроизведения").accessibilityValue(clock(time))
                .accessibilityAdjustableAction { direction in seek(time + (direction == .increment ? 5 : -5)) }
                HStack {
                    Text(clock(time)); Spacer(); Text(clock(length))
                }.font(.caption.monospacedDigit()).foregroundStyle(Studio.muted).accessibilityHidden(true)
            }
            ViewThatFits(in: .horizontal) {
                HStack { toggle; Spacer(minLength: 8); rate; addMark }
                VStack(alignment: .leading, spacing: 2) { toggle; rate; addMark }
            }
        }
        .disabled(model.recording || model.busy)
        .task(id: audio.path) {
            saved = listening.position(id)
            if let asset = try? AVAudioFile(forReading: audio), asset.processingFormat.sampleRate > 0 {
                localDuration = Double(asset.length) / asset.processingFormat.sampleRate
            }
        }.onChange(of: playback.file) { _ in saved = listening.position(id) }
    }

    private var toggle: some View {
        Button { if playing { playback.pause() } else { model.play(audio) } } label: {
            HStack(spacing: 7) {
                if playing { PlayingBars(active: true) } else { Image(systemName: "play.fill").accessibilityHidden(true) }
                Text(playing ? "Пауза" : (time > 0 ? "Продолжить" : "Слушать"))
            }
                .font(.headline).fixedSize(horizontal: true, vertical: false)
                .padding(.horizontal, 14).frame(minHeight: 44)
                .foregroundStyle(Studio.card)
                .modifier(DeskGlass(radius: 22, tint: Studio.accent, interactive: true))
        }.buttonStyle(.borderless)
    }
    private var rate: some View {
        Menu {
            Picker("Скорость", selection: Binding(get: { listening.rate }, set: { playback.setRate($0) })) {
                ForEach(ListeningLibrary.rates, id: \.self) { value in Text(rateLabel(value)).tag(value) }
            }
        } label: { Text(rateLabel(listening.rate)).fixedSize(horizontal: true, vertical: false).padding(.horizontal, 6).frame(minHeight: 44) }
        .buttonStyle(.borderless).accessibilityLabel("Скорость воспроизведения").accessibilityValue(rateLabel(listening.rate))
    }
    private var addMark: some View {
        Button { bookmark(drag ?? playback.position(for: id)) } label: {
            Label("Закладка", systemImage: "bookmark.badge.plus").fixedSize(horizontal: true, vertical: false).frame(minHeight: 44)
        }.buttonStyle(.borderless).accessibilityLabel("Добавить закладку в текущей позиции")
    }
    private func seek(_ value: Double) {
        saved = min(length, max(0, value)); playback.seek(id, to: saved, duration: length)
    }
    private func rateLabel(_ value: Float) -> String {
        value.formatted(.number.locale(Locale(identifier: "ru_RU")).precision(.fractionLength(0...2))) + "×"
    }
}
