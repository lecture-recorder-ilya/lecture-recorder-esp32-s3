import Cocoa
let dir = CommandLine.arguments[1]
for size in [16,32,64,128,256,512,1024] {
 let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:size,pixelsHigh:size,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState()
 NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:rep)
 let c=NSGraphicsContext.current!.cgContext
 c.scaleBy(x:CGFloat(size)/1024,y:CGFloat(size)/1024)
 NSColor(srgbRed:1,green:0.35,blue:0.23,alpha:1).setFill()
 NSBezierPath(roundedRect:NSRect(x:62,y:62,width:900,height:900),xRadius:210,yRadius:210).fill()
 NSColor(calibratedWhite:1,alpha:0.97).setFill()
 NSBezierPath(roundedRect:NSRect(x:409,y:410,width:206,height:368),xRadius:103,yRadius:103).fill()
 let arc=NSBezierPath();arc.move(to:NSPoint(x:327,y:540));arc.line(to:NSPoint(x:327,y:460));arc.curve(to:NSPoint(x:697,y:460),controlPoint1:NSPoint(x:327,y:213),controlPoint2:NSPoint(x:697,y:213));arc.line(to:NSPoint(x:697,y:540));arc.lineWidth=46;arc.lineCapStyle = .round;NSColor.white.setStroke();arc.stroke()
 let stem=NSBezierPath();stem.move(to:NSPoint(x:512,y:287));stem.line(to:NSPoint(x:512,y:208));stem.move(to:NSPoint(x:427,y:208));stem.line(to:NSPoint(x:597,y:208));stem.lineWidth=46;stem.lineCapStyle = .round;stem.stroke()
 NSGraphicsContext.restoreGraphicsState()
 let data=rep.representation(using:.png,properties:[:])!
 var names:[String]=[]
 if size<=512 { names.append("icon_\(size)x\(size).png") }
 if size>=32 { names.append("icon_\(size/2)x\(size/2)@2x.png") }
 for name in names { try data.write(to:URL(fileURLWithPath:dir).appendingPathComponent(name)) }
 if size==1024 {try data.write(to:URL(fileURLWithPath:"outputs/recorder-icon.png"))}
}
