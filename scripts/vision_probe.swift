// Faces and text boxes in still frames, via Apple's Vision framework (on every Mac, nothing to install).
//
//     swiftc -O scripts/vision_probe.swift -o scripts/.bin/vision_probe    (scripts/critic.py compiles it on first use)
//     scripts/.bin/vision_probe frame1.png frame2.png ...                  -> one JSON object per line
//
// Boxes are fractions of the image with the origin at the TOP left: {"x","y","w","h"}.
// Text lines carry the recognizer's confidence; the critic sizes text by line height.
// "person" is a 36x64 grid (rows top to bottom, "1" = mostly person) from person segmentation, so the critic never
// counts the presenter's dark shirt as empty space.
import AppKit
import Foundation
import Vision

func box(_ r: CGRect) -> [String: Double] {
    ["x": Double(r.minX), "y": Double(1 - r.maxY), "w": Double(r.width), "h": Double(r.height)]
}

var failed = false
for path in CommandLine.arguments.dropFirst() {
    var out: [String: Any] = ["image": path]
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        out["error"] = "unreadable"
        failed = true
        print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
        continue
    }
    let faces = VNDetectFaceRectanglesRequest()
    let text = VNRecognizeTextRequest()
    text.recognitionLevel = .accurate
    text.usesLanguageCorrection = false
    let person = VNGeneratePersonSegmentationRequest()
    person.qualityLevel = .balanced
    person.outputPixelFormat = kCVPixelFormatType_OneComponent8
    do {
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([faces, text, person])
    } catch {
        // a failed analysis must never read as "no faces, no text"
        out["error"] = "vision: \(error.localizedDescription)"
        failed = true
        print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
        continue
    }
    if let mask = person.results?.first?.pixelBuffer {
        CVPixelBufferLockBaseAddress(mask, .readOnly)
        let mw = CVPixelBufferGetWidth(mask), mh = CVPixelBufferGetHeight(mask)
        let stride = CVPixelBufferGetBytesPerRow(mask)
        let base = CVPixelBufferGetBaseAddress(mask)!.assumingMemoryBound(to: UInt8.self)
        var rows: [String] = []
        for gy in 0..<64 {
            var row = ""
            for gx in 0..<36 {
                var on = 0, n = 0
                let y0 = gy * mh / 64, y1 = max(y0 + 1, (gy + 1) * mh / 64)
                let x0 = gx * mw / 36, x1 = max(x0 + 1, (gx + 1) * mw / 36)
                for y in Swift.stride(from: y0, to: y1, by: 2) {
                    for x in Swift.stride(from: x0, to: x1, by: 2) {
                        n += 1
                        if base[y * stride + x] > 127 { on += 1 }
                    }
                }
                row += (n > 0 && on * 10 >= n * 4) ? "1" : "0"
            }
            rows.append(row)
        }
        CVPixelBufferUnlockBaseAddress(mask, .readOnly)
        out["person"] = rows
    }
    out["w"] = cg.width
    out["h"] = cg.height
    out["faces"] = (faces.results ?? []).map { box($0.boundingBox) }
    out["text"] = (text.results ?? []).compactMap { obs -> [String: Any]? in
        guard let c = obs.topCandidates(1).first else { return nil }
        return ["s": c.string, "conf": Double(c.confidence), "box": box(obs.boundingBox)]
    }
    print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
}
exit(failed ? 1 : 0)
