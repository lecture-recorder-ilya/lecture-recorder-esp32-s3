import Foundation

enum OfflineNoteSelection {
    private static let domain = #/\b(?:функци|производн|масса|масс[уы]|плотност|величин|импульс|сил[ауы]|треугольник|площад|предел|интеграл|матриц|вектор|теорем|коэффициент|уравнен|последовательност|множеств|вероятност|гипотенуз|кинетическ|энерги|скорост|ускорени|сопротивлен|напряжени|температур|давлени|электрическ|электромагнит|молекул|атом|кислород|фермент|клетк|организм|морфем|падеж|подлежащ|сказуем|алгоритм|рекурси|компилятор|переменн|массив|байт|битов|параметр|статистик|дисперси|инфляци|спрос|эластичност)\p{L}*/#
    private static let relation = #/\b(?:равен|равна|равно|равны|называется|называют|понимают|понимается|измеряется|определяется|пропорциональн\p{L}*|состоит из|представляет собой|зависит от)\b|[—–]\s*это\b/#
    private static let definition = #/\b(?:определяется как|по определению|под термином)\b/#
    private static let question = #/^(?:(?:а |и |так )?(?:как|зачем|почему|когда|где|кто|что|чем|чему|сколько|каков\p{L}*|како[йея]|разве)\b)|\bли\b|\?/#
    private static let context = #/\b(?:например|допустим|представьте|предположим|возможно|наверно\p{L}*|кажется|вероятно|сказал\p{L}*|спросил\p{L}*|говорит|по словам|условно|захотите|предлагает|сказано|считаю|не уверен\p{L}*|не помню|вы хотите|я думаю|если хотите|в качестве примера)\b/#
    private static let nonAcademic = #/\b(?:микрофон включ\p{L}*|проверяем звук|вы слышите|меня слышно|автобус|магазин|остановк\p{L}*|сосед\p{L}*|обед\p{L}*|сегодня|сейчас|на улице|в моей|у меня|здесь|переменк\p{L}*|привет|извините|чайник|кофе|столов\p{L}*)\b/#
    private static let unfinished = #/\b(?:и|но|или|если|когда|котор\p{L}*|потому|в|к|на|из|по|до|от|за|с|для|без|при|не|ни|это|такой|равен|равна|равно|свою|свой|этого)[\s.,:!;…]*$/#
    private static let action = #/\b(?:решите|прочитайте|подготовьте|сдайте|напишите|повторите|выучите|выполните|вычислите|докажите|постройте)\b/#
    private static let infinitive = #/\b(?:решить|прочитать|подготовить|сдать|написать|повторить|выучить|выполнить|вычислить|доказать|построить)\b/#
    private static let assignmentTime = #/\b(?:на дом|дома|домашн(?:ее задание|яя работа)|к следующ(?:ей паре|ему занятию|ему уроку|ей лекции))\b/#
    private static let assignmentNoun = #/\b(?:задач\p{L}*|упражнени\p{L}*|параграф\p{L}*|глав[уаые]|пример\p{L}*|уравнени\p{L}*|теорем\p{L}*|конспект\p{L}*|доклад\p{L}*|отчет\p{L}*|доказательств\p{L}*|график\p{L}*|таблиц\p{L}*|документ\p{L}*)\b/#
    private static let assignmentLabel = #/^(?:ваше )?домашн(?:ее задание|яя работа)\s*[:—–-]/#
    private static let assignedFirst = #/^(?:дома|на дом|(?:ваше )?домашн(?:ее задание|яя работа)|задание на дом|к следующ(?:ей паре|ему занятию|ему уроку|ей лекции))\b/#
    private static let imperativeFirst = #/^\p{L}+/#
    private static let obligation = #/\b(?:нужно|надо|необходимо)\b/#
    private static let fill = #/\b(?:не|нет|отмен\p{L}*|никто|возможно|по желанию|можете|кто хочет|хотите|если|когда|вместо|вчера|в прошл\p{L}*|в классе|в аудитории|я|мне|мы|нам)\b/#
    private static let cancelWork = #/\b(?:(?:домашн(?:ее задание|его задания|яя работа|ей работы)|задани[ея])(?: на дом| сегодня)?\s+(?:не будет|нет|отмен\p{L}*)|отменяю (?:все |всё )?(?:задани[ея]|домашн\p{L}* (?:задани\p{L}*|работ\p{L}*))|на дом (?:ничего )?не зада(?:ю|ем))\b/#
    private static let correction = #/^(?:нет\b|поправка\b|точнее\b|стоп\b|я ошиб\p{L}*\b|погодите\b|отмен\p{L}*\b|это неверно\b|не так\b)/#

    static func normalized(_ text: String) -> String {
        text.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    static func report(_ rows: [[String: Any]]) -> [String: Any] {
        let segments = rows.enumerated().map { index, value in
            var row = value
            row["id"] = index
            return row
        }
        var points: [[String: Any]] = [], homework: [[String: Any]] = []
        var seenPoints = Set<String>(), seenTasks = Set<String>()
        for (index, row) in segments.enumerated() {
            guard let quote = row["text"] as? String, let start = row["start"] as? Double,
                  let end = row["end"] as? Double, start.isFinite, end.isFinite, start >= 0,
                  end > start, end <= 8 * 3600 else { continue }
            let normalizedQuote = normalized(quote)
            let line = normalizedQuote.replacingOccurrences(of: "ё", with: "е")
            if line.contains(cancelWork), !line.contains(question), !line.contains(context) {
                homework.removeAll(); seenTasks.removeAll()
            }
            guard row["needs_review"] as? Bool == false, !line.contains(question), !line.contains(context),
                  !line.contains(nonAcademic), !line.contains(unfinished),
                  line.split(separator: " ").count >= 4, line.count <= 320, !line.hasSuffix("…"),
                  !line.hasSuffix("..."), !line.hasSuffix(","), !line.hasSuffix(":"),
                  !nearCorrection(segments, index, end: end), !exampleBefore(segments, index, start: start) else { continue }
            let directOrder = line.contains(assignedFirst) || line.firstMatch(of: imperativeFirst).map { String($0.output).contains(action) } == true
            let task = directOrder && line.contains(assignmentTime) && line.contains(assignmentNoun) && !line.contains(fill)
                && (line.contains(action) || ((line.contains(assignmentLabel) || line.contains(obligation)) && line.contains(infinitive)))
            let conditional = line.hasPrefix("если ") && line.contains(#/\bто\b/#)
            let plainDefinition = line.range(of: " это ").map { split in
                let term = String(line[..<split.lowerBound])
                return term.split(separator: " ").count <= 4 && term.contains(domain)
            } ?? false
            let concept = !line.contains(assignmentTime) && !line.contains(action) && !line.hasPrefix("то ")
                && (line.contains(domain) && (line.contains(relation) || plainDefinition || conditional) || line.contains(definition) && line.contains(relation))
                && (!line.hasPrefix("если ") || conditional)
            guard task || concept else { continue }
            let key = normalizedQuote.trimmingCharacters(in: .punctuationCharacters)
            let signature = "\(index)|\(Int((start * 1000).rounded()))|\(Int((end * 1000).rounded()))|\(normalizedQuote)"
            var citation: [String: Any] = ["segment_id": index, "quote": quote, "start": start, "end": end,
                                           "source_status": "confirmed", "source_fingerprint": sha256(Data(signature.utf8)),
                                           "selection_method": "verbatim_fallback"]
            if task {
                if seenTasks.insert(key).inserted { citation["task"] = quote; homework.append(citation) }
            } else if seenPoints.insert(key).inserted { points.append(citation) }
        }
        let limit = 6
        if points.count > limit {
            points = (0..<limit).map { points[$0 * (points.count - 1) / (limit - 1)] }
        }
        return ["topic": "Расшифровка записи", "segments": segments, "summary": points.compactMap { $0["quote"] },
                "summary_evidence": points, "homework": homework, "summary_method": "ios_extractive"]
    }

    private static func nearCorrection(_ rows: [[String: Any]], _ index: Int, end: Double) -> Bool {
        guard index + 1 < rows.count, let start = rows[index + 1]["start"] as? Double, start - end <= 3,
              let next = rows[index + 1]["text"] as? String else { return false }
        return normalized(next).contains(correction)
    }

    private static func exampleBefore(_ rows: [[String: Any]], _ index: Int, start: Double) -> Bool {
        guard index > 0, let end = rows[index - 1]["end"] as? Double, start - end <= 2,
              let text = rows[index - 1]["text"] as? String else { return false }
        let previous = normalized(text)
        return previous.contains(context) && (previous.hasSuffix(":") || previous == "например" || previous == "допустим")
    }
}
