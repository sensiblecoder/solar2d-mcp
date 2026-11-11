// cutout: lift the foreground subject(s) out of an image with Apple Vision and write a
// transparent PNG. The same model as Photos' "Copy Subject"; runs on-device (macOS 14+).
//
//   cutout <input image> <output.png>
//
// Prints {"instances": N} on success. Exit 3 when Vision finds no subject.

import CoreImage
import Foundation
import ImageIO
import Vision

func fail(_ message: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

let args = CommandLine.arguments
guard args.count == 3 else { fail("usage: cutout <input image> <output.png>", 2) }
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])

guard let source = CGImageSourceCreateWithURL(inURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fail("cannot read image: \(inURL.path)")
}

let request = VNGenerateForegroundInstanceMaskRequest()
let handler = VNImageRequestHandler(cgImage: image, options: [:])
do {
    try handler.perform([request])
} catch {
    fail("Vision failed: \(error.localizedDescription)")
}
guard let observation = request.results?.first, !observation.allInstances.isEmpty else {
    fail("no foreground subject found", 3)
}

do {
    let masked = try observation.generateMaskedImage(
        ofInstances: observation.allInstances, from: handler, croppedToInstancesExtent: false)
    let context = CIContext()
    try context.writePNGRepresentation(
        of: CIImage(cvPixelBuffer: masked), to: outURL, format: .RGBA8,
        colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!)
} catch {
    fail("cannot write cutout: \(error.localizedDescription)")
}
print("{\"instances\": \(observation.allInstances.count)}")
