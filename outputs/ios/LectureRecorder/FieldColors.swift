import SwiftUI

enum Studio {
    static let background = adaptive(0xF7F5EF, 0x121B19)
    static let panel = adaptive(0xFFFDF8, 0x202D29)
    static let hero = adaptive(0xE1F1E9, 0x213E34)
    static let line = adaptive(0xD4D9CF, 0x3E504A)
    static let ink = adaptive(0x1D302E, 0xF7F5EF)
    static let muted = adaptive(0x52635D, 0xB5C4BA)
    static let accent = adaptive(0x146B5C, 0x75D9BC)
    static let warning = adaptive(0x88511A, 0xF1BD84)
    static let card = rgb(0x193531)
    static let cardInk = rgb(0xF7F5EF)
    static let cardMuted = rgb(0xBECFC7)
    static let margin = rgb(0x61CFB2)
    static let mint = rgb(0x7DDCC0)
    static let live = rgb(0xFFBAA8)

    private static func rgb(_ hex: Int) -> Color {
        Color(.sRGB, red: Double(hex >> 16) / 255, green: Double((hex >> 8) & 255) / 255,
              blue: Double(hex & 255) / 255)
    }

    private static func adaptive(_ light: Int, _ dark: Int) -> Color {
        Color(uiColor: UIColor { trait in UIColor(rgb(trait.userInterfaceStyle == .dark ? dark : light)) })
    }
}
