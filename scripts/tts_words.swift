// Speak a script with the macOS system voice and record when each word starts, for scripts/words.py.
//
//     swiftc -O scripts/tts_words.swift -o scripts/.bin/tts_words        (words.py compiles it on first use)
//     scripts/.bin/tts_words script.txt out.caf [voice name or identifier] [rate 0-1]
//
// AVSpeechSynthesizer writes the audio buffer by buffer and calls its delegate as each word begins, so the number of
// samples written so far at that call is the word's start. Measured against silence detection it lands within about
// 30 ms. Prints one JSON object per word ({"w", "loc", "len", "sample"}), then {"rate", "frames"}.
import AVFoundation
import Foundation

var frames: Int64 = 0
var marks: [[String: Any]] = []
var text = ""

class Listener: NSObject, AVSpeechSynthesizerDelegate {
    func speechSynthesizer(_ s: AVSpeechSynthesizer, willSpeakRangeOfSpeechString r: NSRange, utterance: AVSpeechUtterance) {
        let w = Range(r, in: text).map { String(text[$0]) } ?? ""
        marks.append(["w": w, "loc": r.location, "len": r.length, "sample": frames])
    }
}

let args = CommandLine.arguments
guard args.count >= 3, let t = try? String(contentsOfFile: args[1], encoding: .utf8) else {
    FileHandle.standardError.write("usage: tts_words script.txt out.caf [voice] [rate]\n".data(using: .utf8)!)
    exit(2)
}
text = t
let out = URL(fileURLWithPath: args[2])
let synth = AVSpeechSynthesizer()
let listener = Listener()
synth.delegate = listener
let u = AVSpeechUtterance(string: text)
if args.count > 3 && !args[3].isEmpty {
    let want = args[3].lowercased()
    guard let v = AVSpeechSynthesisVoice.speechVoices().first(where: { $0.identifier.lowercased() == want || $0.name.lowercased() == want }) else {
        FileHandle.standardError.write("voice \(args[3]) not found (System Settings > Accessibility > Spoken Content lists them)\n".data(using: .utf8)!)
        exit(2)
    }
    u.voice = v
}
if args.count > 4, let r = Float(args[4]) { u.rate = max(AVSpeechUtteranceMinimumSpeechRate, min(AVSpeechUtteranceMaximumSpeechRate, r)) }
var done = false
var file: AVAudioFile? = nil
var rate: Double = 0
var failure: String? = nil
synth.write(u) { buf in
    guard let pcm = buf as? AVAudioPCMBuffer else { return }
    if pcm.frameLength == 0 { done = true; return }
    do {
        if file == nil {
            rate = pcm.format.sampleRate
            file = try AVAudioFile(forWriting: out, settings: pcm.format.settings, commonFormat: pcm.format.commonFormat,
                                   interleaved: pcm.format.isInterleaved)
        }
        try file!.write(from: pcm)
    } catch {
        failure = "\(error)"
        done = true
    }
    frames += Int64(pcm.frameLength)
}
let started = Date()
while !done && Date().timeIntervalSince(started) < 600 { RunLoop.current.run(until: Date().addingTimeInterval(0.01)) }
if let f = failure { FileHandle.standardError.write("write failed: \(f)\n".data(using: .utf8)!); exit(1) }
if !done || frames == 0 { FileHandle.standardError.write("the synthesizer produced no audio\n".data(using: .utf8)!); exit(1) }
for m in marks { print(String(data: try! JSONSerialization.data(withJSONObject: m), encoding: .utf8)!) }
print(String(data: try! JSONSerialization.data(withJSONObject: ["rate": rate, "frames": frames]), encoding: .utf8)!)
