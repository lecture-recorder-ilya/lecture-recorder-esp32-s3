import Cocoa

let iconset = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)

let ink = NSColor(srgbRed: 25 / 255, green: 53 / 255, blue: 49 / 255, alpha: 1)
let paper = NSColor(srgbRed: 247 / 255, green: 245 / 255, blue: 239 / 255, alpha: 1)
let margin = NSColor(srgbRed: 97 / 255, green: 207 / 255, blue: 178 / 255, alpha: 1)

func drawIcon(size: Int, fullBleed: Bool) -> Data {
    let alpha: CGImageAlphaInfo = fullBleed ? .noneSkipLast : .premultipliedLast
    let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                            bytesPerRow: size * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: alpha.rawValue)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
    let scale = CGFloat(size) / 1024
    NSGraphicsContext.current!.cgContext.scaleBy(x: scale, y: scale)
    ink.setFill()
    if fullBleed {
        NSBezierPath(rect: NSRect(x: 0, y: 0, width: 1024, height: 1024)).fill()
    } else {
        NSBezierPath(roundedRect: NSRect(x: 50, y: 50, width: 924, height: 924),
                     xRadius: 210, yRadius: 210).fill()
    }
    let page = NSRect(x: 257, y: 199, width: 510, height: 626)
    let sheet = NSBezierPath(roundedRect: page, xRadius: 57, yRadius: 57)
    paper.setFill()
    sheet.fill()
    sheet.addClip()
    margin.setFill()
    NSBezierPath(rect: NSRect(x: 345, y: page.minY, width: 39, height: page.height)).fill()
    ink.setFill()
    for (height, width) in [(614, 230), (502, 155), (390, 210)] {
        NSBezierPath(roundedRect: NSRect(x: 440, y: height, width: width, height: 33),
                     xRadius: 16.5, yRadius: 16.5).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    return NSBitmapImageRep(cgImage: context.makeImage()!).representation(using: .png, properties: [:])!
}

for size in [16, 32, 64, 128, 256, 512, 1024] {
    let png = drawIcon(size: size, fullBleed: false)
    if [16, 32, 128, 256, 512].contains(size) {
        try png.write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    }
    let half = size / 2
    if [16, 32, 128, 256, 512].contains(half) {
        try png.write(to: iconset.appendingPathComponent("icon_\(half)x\(half)@2x.png"))
    }
    if size == 1024 {
        try png.write(to: URL(fileURLWithPath: "outputs/recorder-icon.png"))
    }
}
if CommandLine.arguments.count > 2 {
    try drawIcon(size: 1024, fullBleed: true).write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
}
