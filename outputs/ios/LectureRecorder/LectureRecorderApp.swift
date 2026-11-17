import SwiftUI
import UniformTypeIdentifiers

@main struct LectureRecorderApp: App {
    @StateObject private var model = PhoneModel()
    var body: some Scene {
        WindowGroup {
            TabView {
                RecordScreen(model: model).tabItem { Label("Запись", systemImage: "mic") }
                LibraryScreen(model: model).tabItem { Label("Библиотека", systemImage: "books.vertical") }
                SettingsScreen(model: model).tabItem { Label("Настройки", systemImage: "gearshape") }
            }
            .tint(Color(red: 1, green: 0.35, blue: 0.23)).preferredColorScheme(.dark)
        }
    }
}

func clock(_ value: Double) -> String {
    let seconds = max(0, Int(value))
    return String(format: "%02d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
}

struct RecordScreen: View {
    @ObservedObject var model: PhoneModel
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Text("Сохрани пару. Вернись к главному.").foregroundStyle(.secondary)
                    VStack(spacing: 20) {
                        Label(model.recording ? "Идёт запись" : "Микрофон телефона", systemImage: model.recording ? "record.circle.fill" : "mic.fill")
                        Text(clock(model.seconds)).font(.system(size: 46, weight: .medium, design: .monospaced)).minimumScaleFactor(0.6)
                        Button(model.recording ? "Завершить и сохранить" : "Начать запись") { if model.recording { model.stopRecording() } else { model.startRecording() } }
                            .buttonStyle(.borderedProminent).controlSize(.large).disabled(model.busy)
                        Text("Запись остаётся на телефоне. Mac и ESP для записи не нужны.").font(.footnote).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity).padding(24).background(Color.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 22))
                    Text(model.message).font(.callout).accessibilityAddTraits(.updatesFrequently)
                    if model.recording { Text("Экран можно заблокировать. Звонок или системное прерывание завершит и сохранит доступный звук.").font(.footnote).foregroundStyle(.secondary) }
                    Text("Очистка, расшифровка с таймкодами и конспект готовятся на Mac после переноса.").foregroundStyle(.secondary)
                }.padding(20)
            }.navigationTitle("Новая запись")
        }
    }
}

struct LibraryScreen: View {
    @ObservedObject var model: PhoneModel
    @State private var importing = false
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button { importing = true } label: { Label("Загрузить аудио или видео", systemImage: "square.and.arrow.down") }.disabled(model.busy || model.recording)
                    Text(model.message).font(.footnote).foregroundStyle(.secondary)
                }
                if !model.drafts.isEmpty {
                    Section("Незавершённые записи") {
                        ForEach(model.drafts, id: \.path) { file in Button("Восстановить запись") { model.importAudio(file, removeDraft: true) }.disabled(model.busy || model.recording) }
                    }
                }
                Section("Расшифровки и конспекты") {
                    if model.notes.isEmpty { Text("Появятся после обработки на Mac").foregroundStyle(.secondary) }
                    ForEach(model.notes) { note in NavigationLink(note.report.topic ?? note.report.subject ?? "Занятие") { ReaderScreen(model: model, note: note) } }
                }
                Section("Аудиозаписи") {
                    if model.recordings.isEmpty { Text("Пока нет записей").foregroundStyle(.secondary) }
                    ForEach(model.recordings, id: \.path) { file in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(file.lastPathComponent.replacingOccurrences(of: "lecture-", with: "").replacingOccurrences(of: ".wav", with: "")).font(.subheadline)
                            HStack { Button { model.play(file) } label: { Label("Слушать", systemImage: "play.fill") }.buttonStyle(.bordered); ShareLink(item: file) { Image(systemName: "square.and.arrow.up").accessibilityLabel("Поделиться записью") }.buttonStyle(.bordered) }
                        }.padding(.vertical, 6)
                    }
                    Button("Остановить воспроизведение") { model.stopPlayback() }
                }
            }.navigationTitle("Библиотека")
            .fileImporter(isPresented: $importing, allowedContentTypes: [.audio, .movie], allowsMultipleSelection: false) { result in
                switch result { case .success(let files): if let file = files.first { model.importAudio(file) }; case .failure(let error): model.message = error.localizedDescription }
            }
        }
    }
}

struct ReaderScreen: View {
    @ObservedObject var model: PhoneModel
    let note: LectureNote
    @State private var selected = 0
    var current: LectureNote { model.notes.first { $0.id == note.id } ?? note }
    var body: some View {
        List {
            Picker("Материалы", selection: $selected) { Text("Текст").tag(0); Text("Конспект").tag(1) }.pickerStyle(.segmented)
            if selected == 0 {
                if model.files.localAudio(note.file) == nil { Text("Аудиокопии на этом телефоне нет. Полная запись доступна на Mac.").font(.footnote).foregroundStyle(.secondary) }
                ForEach(Array((current.report.segments ?? []).enumerated()), id: \.offset) { _, segment in
                    Button {
                        if let file = model.files.localAudio(note.file) { model.play(file, at: segment.start ?? 0) }
                    } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            if let start = segment.start { Text(clock(start)).font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
                            Text(segment.text).foregroundStyle(.primary).multilineTextAlignment(.leading)
                            if segment.needs_review == true { Label("Проверь по записи", systemImage: "ear.badge.exclamationmark").font(.caption).foregroundStyle(.orange) }
                        }.padding(.vertical, 6)
                    }.buttonStyle(.plain).disabled(model.files.localAudio(note.file) == nil || model.recording)
                }
            } else {
                if let overview = current.report.overview, !overview.isEmpty { Text(overview) }
                ForEach(Array((current.report.summary ?? []).enumerated()), id: \.offset) { _, point in Text(point) }
            }
            Button("Остановить звук") { model.stopPlayback() }
        }.navigationTitle(current.report.topic ?? current.report.subject ?? "Занятие").navigationBarTitleDisplayMode(.inline)
    }
}

struct SettingsScreen: View {
    @ObservedObject var model: PhoneModel
    @State private var host = ""
    @State private var code = ""
    @State private var disconnect = false
    var body: some View {
        NavigationStack {
            Form {
                Section("Телефон и Mac") {
                    Text(model.macName)
                    Text("Открой на Mac «Настройки → Телефон и Mac → Подключить телефон». Оба устройства должны быть в одной Wi-Fi сети.").font(.footnote)
                    TextField("Адрес Mac с его экрана", text: $host).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    TextField("Код Mac · 12 символов", text: $code).textInputAutocapitalization(.characters).autocorrectionDisabled()
                    if !model.verification.isEmpty { Text(model.verification).font(.largeTitle.monospacedDigit()); Text("Сравни цифры и подтверди подключение на Mac") }
                    Button(model.pairing ? "Ожидаю подтверждения…" : "Подключить Mac") { model.connect(host: host, code: code) }.disabled(model.pairing || model.recording)
                    if model.pairing { Button("Отмена") { model.cancelPairing() } }
                    Text(model.message).font(.footnote).foregroundStyle(.secondary)
                    Button("Отключить Mac", role: .destructive) { disconnect = true }.disabled(model.recording || model.pairing)
                }
                Section("Перенос и обновления") {
                    Text("Открой приложение рядом с Mac. Новые записи и расшифровки переносятся по Wi-Fi автоматически. После подтверждения Mac аудиокопия остаётся в библиотеке телефона.")
                    Text("В фоне iOS может приостановить перенос. Продолжающаяся запись сохраняется локально.")
                    Text("Версии приложения для iPhone устанавливаются через TestFlight или App Store. APK для Android сюда не подходит.")
                    Text("Версия 0.5.3 · iOS / iPadOS 16+").font(.footnote).foregroundStyle(.secondary)
                }
            }.navigationTitle("Настройки")
            .confirmationDialog("Отключить Mac? Записи и тексты останутся на телефоне.", isPresented: $disconnect) { Button("Отключить Mac", role: .destructive) { model.disconnect() } }
        }
    }
}
