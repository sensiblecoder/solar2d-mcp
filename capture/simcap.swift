// simcap — record one app window through ScreenCaptureKit: native pixels, up to 60fps, the app's own audio.
//
//   simcap <out.mov> [--app "Corona Simulator"] [--title SUBSTR] [--fps 60] [--codec hevc|prores]
//                    [--aspect W:H] [--max-seconds N] [--stop-file PATH] [--no-audio]
//   simcap --list
//
// --aspect crops to the largest W:H rect anchored to the window's bottom edge, which drops the
// title bar of a simulator window whose content has that aspect. Recording stops on SIGINT/SIGTERM,
// when --stop-file appears, or after --max-seconds. Prints "recording ..." once frames flow and a
// final "done {json}" line with the stats.
import AppKit
import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

_ = NSApplication.shared  // CoreGraphics needs a window-server connection before SCK is touched

var args = Array(CommandLine.arguments.dropFirst())
func opt(_ k: String) -> String? {
  guard let i = args.firstIndex(of: k), i + 1 < args.count else { return nil }
  let v = args[i + 1]; args.removeSubrange(i...i + 1); return v
}
func flag(_ k: String) -> Bool {
  guard let i = args.firstIndex(of: k) else { return false }
  args.remove(at: i); return true
}
func fail(_ msg: String, _ code: Int32 = 1) -> Never { fputs("error: \(msg)\n", stderr); exit(code) }

let appName = opt("--app") ?? "Corona Simulator"
let titleFilter = opt("--title")
let fps = max(1, Int(opt("--fps") ?? "60") ?? 60)
let codec = opt("--codec") ?? "hevc"
let aspect: CGFloat? = opt("--aspect").flatMap { s in
  let p = s.split(separator: ":").compactMap { Double($0) }
  return p.count == 2 && p[1] > 0 ? CGFloat(p[0] / p[1]) : nil
}
let maxSeconds = Double(opt("--max-seconds") ?? "600") ?? 600
let stopFile = opt("--stop-file")
let noAudio = flag("--no-audio")
let list = flag("--list")
let outPath = args.first

final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate {
  let writer: AVAssetWriter
  let video: AVAssetWriterInput
  let audio: AVAssetWriterInput?
  let queue = DispatchQueue(label: "simcap.writer")
  var started = false
  var frames = 0
  var dropped = 0
  var failure: Error?

  init(writer: AVAssetWriter, video: AVAssetWriterInput, audio: AVAssetWriterInput?) {
    self.writer = writer; self.video = video; self.audio = audio
  }

  func stream(_ s: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
    guard sb.isValid else { return }
    switch type {
    case .screen:
      // Only complete frames carry pixels; idle/blank status buffers are skipped.
      guard let att = CMSampleBufferGetSampleAttachmentsArray(sb, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
            let raw = att.first?[.status] as? Int, SCFrameStatus(rawValue: raw) == .complete else { return }
      if !started {
        writer.startWriting(); writer.startSession(atSourceTime: sb.presentationTimeStamp); started = true
      }
      if video.isReadyForMoreMediaData { video.append(sb); frames += 1 } else { dropped += 1 }
    case .audio:
      if started, let a = audio, a.isReadyForMoreMediaData { a.append(sb) }
    default: break
    }
  }

  func stream(_ s: SCStream, didStopWithError error: Error) { failure = error }
}

func findWindow() async throws -> SCWindow {
  // Not on-screen-only: a window behind another one still renders and is still captured.
  let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
  if list {
    for w in content.windows where w.frame.width > 200 && w.frame.height > 200 {
      print(w.windowID, w.owningApplication?.applicationName ?? "?", "|", w.title ?? "", w.frame, w.isOnScreen ? "on-screen" : "off-screen")
    }
    exit(0)
  }
  let candidates = content.windows.filter { (w: SCWindow) -> Bool in
    guard (w.owningApplication?.applicationName ?? "") == appName, w.frame.width > 200, w.frame.height > 200 else { return false }
    guard let t = titleFilter else { return true }
    return (w.title ?? "").localizedCaseInsensitiveContains(t)
  }
  let area = { (w: SCWindow) in w.frame.width * w.frame.height }
  let pick = candidates.filter { (w: SCWindow) in w.isOnScreen }.max { area($0) < area($1) } ?? candidates.max { area($0) < area($1) }
  guard let win = pick else { fail("no '\(appName)' window\(titleFilter.map { " titled *\($0)*" } ?? "") (is the simulator running?)", 2) }
  return win
}

func run() async throws {
  let win = try await findWindow()
  guard let outPath else { fail("usage: simcap <out.mov> [options]") }

  let filter = SCContentFilter(desktopIndependentWindow: win)
  let scale = CGFloat(filter.pointPixelScale)
  let rect = filter.contentRect
  var src = CGRect(origin: .zero, size: rect.size)
  if let aspect {
    let h = (rect.width / aspect).rounded()
    if h < rect.height { src = CGRect(x: 0, y: rect.height - h, width: rect.width, height: h) }
  }

  let cfg = SCStreamConfiguration()
  cfg.sourceRect = src
  cfg.width = Int(src.width * scale) & ~1
  cfg.height = Int(src.height * scale) & ~1
  cfg.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(fps))
  cfg.queueDepth = 8
  cfg.showsCursor = false
  cfg.ignoreShadowsSingleWindow = true
  cfg.pixelFormat = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
  cfg.colorSpaceName = CGColorSpace.sRGB
  if !noAudio {
    cfg.capturesAudio = true; cfg.sampleRate = 48000; cfg.channelCount = 2; cfg.excludesCurrentProcessAudio = true
  }

  let url = URL(fileURLWithPath: outPath)
  try? FileManager.default.removeItem(at: url)
  let writer = try AVAssetWriter(outputURL: url, fileType: .mov)
  var vs: [String: Any] = [
    AVVideoWidthKey: cfg.width, AVVideoHeightKey: cfg.height,
    AVVideoColorPropertiesKey: [
      AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
      AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
      AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2,
    ],
  ]
  if codec == "prores" {
    vs[AVVideoCodecKey] = AVVideoCodecType.proRes422HQ
  } else {
    vs[AVVideoCodecKey] = AVVideoCodecType.hevc
    vs[AVVideoCompressionPropertiesKey] = [
      AVVideoAverageBitRateKey: 60_000_000, AVVideoExpectedSourceFrameRateKey: fps, AVVideoMaxKeyFrameIntervalKey: fps,
    ]
  }
  let video = AVAssetWriterInput(mediaType: .video, outputSettings: vs)
  video.expectsMediaDataInRealTime = true
  writer.add(video)
  var audio: AVAssetWriterInput?
  if !noAudio {
    let a = AVAssetWriterInput(mediaType: .audio, outputSettings: [
      AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 48000, AVNumberOfChannelsKey: 2, AVEncoderBitRateKey: 256_000,
    ])
    a.expectsMediaDataInRealTime = true
    writer.add(a); audio = a
  }

  let rec = Recorder(writer: writer, video: video, audio: audio)
  let stream = SCStream(filter: filter, configuration: cfg, delegate: rec)
  try stream.addStreamOutput(rec, type: .screen, sampleHandlerQueue: rec.queue)
  if !noAudio { try stream.addStreamOutput(rec, type: .audio, sampleHandlerQueue: rec.queue) }
  try await stream.startCapture()
  let t0 = Date()
  print("recording window \(win.windowID) '\(win.title ?? "")' \(cfg.width)x\(cfg.height) @\(fps) \(codec)\(noAudio ? "" : " +audio") -> \(outPath)")
  fflush(stdout)

  var stop = false
  signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN)
  let sigs = [SIGINT, SIGTERM].map { DispatchSource.makeSignalSource(signal: $0, queue: .main) }
  for s in sigs { s.setEventHandler { stop = true }; s.resume() }
  var reason = "signal"
  while !stop {
    try await Task.sleep(nanoseconds: 50_000_000)
    if rec.failure != nil { reason = "stream error"; break }
    if Date().timeIntervalSince(t0) >= maxSeconds { reason = "max-seconds"; break }
    if let f = stopFile, FileManager.default.fileExists(atPath: f) { reason = "stop-file"; break }
  }
  try? await stream.stopCapture()
  let elapsed = Date().timeIntervalSince(t0)
  rec.queue.sync {}
  if !rec.started { fail("no frames arrived in \(String(format: "%.1f", elapsed))s (screen-recording permission? window minimized?)", 3) }
  video.markAsFinished(); audio?.markAsFinished()
  await writer.finishWriting()
  if writer.status != .completed { fail("writer: \(writer.error.map { "\($0)" } ?? "status \(writer.status.rawValue)")") }

  let stats: [String: Any] = [
    "path": outPath, "width": cfg.width, "height": cfg.height, "frames": rec.frames, "dropped": rec.dropped,
    "seconds": (elapsed * 100).rounded() / 100, "fps": ((Double(rec.frames) / max(elapsed, 0.01)) * 10).rounded() / 10,
    "stopped_by": reason, "stream_error": rec.failure.map { "\($0)" } ?? NSNull(),
  ]
  let json = try JSONSerialization.data(withJSONObject: stats, options: [.sortedKeys])
  print("done " + String(decoding: json, as: UTF8.self))
}

Task {
  do { try await run(); exit(0) } catch { fail("\(error)") }
}
RunLoop.main.run()
