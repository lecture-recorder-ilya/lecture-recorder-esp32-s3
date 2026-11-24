import SwiftUI

enum CapturePhase {
    case ready, starting, recording, saving, importing

    var title: String {
        switch self {
        case .ready: return "Новая запись"
        case .starting: return "Подготовка"
        case .recording: return "Идёт запись"
        case .saving: return "Сохранение"
        case .importing: return "Импорт записи"
        }
    }

    var action: String {
        switch self {
        case .ready: return "Начать запись"
        case .starting: return "Отменить запуск"
        case .recording: return "Завершить и сохранить"
        case .saving: return "Сохраняем…"
        case .importing: return "Импортируем…"
        }
    }
}

struct CaptureDesk: View {
    let phase: CapturePhase
    let source: String
    let elapsed: Double
    let signal: () -> Double
    let notice: String
    let permissionSettings: (() -> Void)?
    let savedTitle: String?
    let capture: () -> Void
    let importAudio: () -> Void
    let settings: () -> Void
    let openSaved: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @ScaledMetric(relativeTo: .largeTitle) private var timerSize = 72.0

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                FieldMark().frame(width: 40, height: 40).accessibilityHidden(true)
                Text("На полях")
                    .font(.system(.largeTitle, design: .serif).weight(.medium))
                    .foregroundStyle(Studio.ink)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                Button(action: settings) {
                    Image(systemName: "gearshape").font(.title3)
                        .frame(width: 44, height: 44)
                        .foregroundStyle(Studio.ink)
                        .background(Studio.panel, in: Circle())
                        .overlay { Circle().strokeBorder(Studio.line) }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Настройки")
            }

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Label(phase.title, systemImage: phase == .recording ? "record.circle.fill" : "mic")
                        .font(.headline)
                        .foregroundStyle(phase == .recording ? Studio.live : Studio.cardInk)
                    Spacer(minLength: 8)
                    if phase == .recording { InputMeter(signal: signal) }
                }

                if phase == .importing {
                    Text(source).font(.title2.weight(.medium)).foregroundStyle(Studio.cardInk)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityLabel("Файл " + source)
                } else {
                    Text(displayTime)
                        .font(.system(size: timerSize, weight: .light).monospacedDigit())
                        .foregroundStyle(Studio.cardInk)
                        .lineLimit(1).minimumScaleFactor(0.35)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityLabel("Длительность записи")
                        .accessibilityValue(spokenTime)
                        .accessibilityAddTraits(.updatesFrequently)

                    HStack(alignment: .center, spacing: 12) {
                        Image(systemName: "mic.fill")
                            .foregroundStyle(Studio.mint).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(phase == .ready ? "Источник при старте" : "Источник").font(.caption).foregroundStyle(Studio.cardMuted)
                            Text(source).font(.body.weight(.medium)).foregroundStyle(Studio.cardInk)
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .padding(.vertical, 5)
                }

                Button(action: capture) {
                    HStack(spacing: 9) {
                        if phase == .saving || phase == .importing {
                            ProgressView().tint(Studio.card)
                        } else {
                            Image(systemName: phase == .ready ? "record.circle" : (phase == .starting ? "xmark" : "stop.fill"))
                                .accessibilityHidden(true)
                        }
                        Text(phase.action)
                            .font(.headline)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 14)
                    .frame(maxWidth: .infinity, minHeight: 50)
                    .foregroundStyle(Studio.card)
                    .background(phase == .recording ? Studio.live : Studio.mint, in: RoundedRectangle(cornerRadius: 13))
                }
                .buttonStyle(DeskButtonStyle())
                .disabled(phase == .saving || phase == .importing)
            }
            .padding(typeSize.isAccessibilitySize ? 18 : 22)
            .background(Studio.card, in: RoundedRectangle(cornerRadius: 24))
            .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: phase)

            if !notice.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    Label(notice, systemImage: "info.circle")
                        .font(.subheadline).foregroundStyle(Studio.ink)
                    if let permissionSettings {
                        Button("Открыть настройки микрофона", action: permissionSettings)
                            .font(.headline).frame(minHeight: 44)
                    }
                }
            }
            if let savedTitle {
                Button(action: openSaved) { SavedRecordingRow(title: savedTitle) }
                    .buttonStyle(DeskButtonStyle())
                    .transition(reduceMotion ? .identity : .opacity)
            }

            Button(action: importAudio) {
                HStack(spacing: 12) {
                    Image(systemName: "square.and.arrow.down")
                        .font(.title3.weight(.medium))
                        .frame(width: 42, height: 46)
                        .foregroundStyle(Studio.accent)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Импорт из Файлов").font(.headline).foregroundStyle(Studio.ink)
                        Text("M4A, MP3, WAV или видео").font(.subheadline).foregroundStyle(Studio.muted)
                    }
                    Spacer(minLength: 4)
                    Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                        .foregroundStyle(Studio.muted).accessibilityHidden(true)
                }
                .multilineTextAlignment(.leading)
                .padding(.vertical, 13).padding(.horizontal, 14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Studio.panel, in: RoundedRectangle(cornerRadius: 17))
                .overlay { RoundedRectangle(cornerRadius: 17).strokeBorder(Studio.line) }
            }
            .buttonStyle(DeskButtonStyle())
            .disabled(phase != .ready)
            .accessibilityElement(children: .combine)
        }
        .padding(.horizontal, 20).padding(.vertical, 16)
        .frame(maxWidth: 580)
        .frame(maxWidth: .infinity)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: savedTitle)
    }

    private var seconds: Int {
        guard elapsed.isFinite, elapsed > 0 else { return 0 }
        return Int(min(8 * 3600, elapsed))
    }

    private var displayTime: String {
        seconds < 3600 ? String(format: "%02d:%02d", seconds / 60, seconds % 60)
            : String(format: "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
    }

    private var spokenTime: String {
        Duration.seconds(seconds).formatted(.units(allowed: [.hours, .minutes, .seconds], width: .wide)
            .locale(Locale(identifier: "ru")))
    }
}

struct SavedRecordingRow: View {
    let title: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .font(.title3).foregroundStyle(Studio.accent).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text("Сохранено в библиотеке").font(.subheadline.weight(.semibold)).foregroundStyle(Studio.accent)
                Text(title).font(.headline).foregroundStyle(Studio.ink)
            }
            Spacer(minLength: 4)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                .foregroundStyle(Studio.accent).accessibilityHidden(true)
        }
        .multilineTextAlignment(.leading)
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .background(Studio.hero, in: RoundedRectangle(cornerRadius: 17))
        .accessibilityElement(children: .combine)
        .accessibilityHint("Открывает материал в библиотеке")
    }
}

private struct FieldMark: View {
    var body: some View {
        Canvas { context, size in
            context.scaleBy(x: size.width / 1024, y: size.height / 1024)
            let tile = CGRect(x: 0, y: 0, width: 1024, height: 1024)
            context.fill(Path(roundedRect: tile, cornerRadius: 244), with: .color(Studio.card))
            let page = Path(roundedRect: CGRect(x: 257, y: 199, width: 510, height: 626), cornerRadius: 57)
            context.fill(page, with: .color(Studio.cardInk))
            context.clip(to: page)
            context.fill(Path(CGRect(x: 345, y: 199, width: 39, height: 626)), with: .color(Studio.margin))
            for (y, width): (CGFloat, CGFloat) in [(377, 230), (489, 155), (601, 210)] {
                let rule = CGRect(x: 440, y: y, width: width, height: 33)
                context.fill(Path(roundedRect: rule, cornerRadius: 16.5), with: .color(Studio.card))
            }
        }
    }
}

private struct InputMeter: View {
    let signal: () -> Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.periodic(from: .now, by: reduceMotion ? 1 : 0.2)) { _ in
            let lit = Int((max(0, min(1, signal())) * 10).rounded())
            HStack(alignment: .bottom, spacing: 2) {
                ForEach(0..<10, id: \.self) { index in
                    Capsule().fill(index < lit ? Studio.mint : Studio.cardMuted.opacity(0.3))
                        .frame(width: 3, height: CGFloat(4 + index * 2))
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Уровень сигнала")
            .accessibilityValue("\(lit) из 10")
            .accessibilityAddTraits(.updatesFrequently)
        }
    }
}

private struct DeskButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(enabled ? (configuration.isPressed ? 0.83 : 1) : 0.62)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.985 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
