import AVFoundation
import ExpoModulesCore
import Foundation

public class SourceAudioModule: Module {
  public func definition() -> ModuleDefinition {
    Name("SourceAudio")
    AsyncFunction("inspect") { (uri: String) async throws -> [String: Int] in
      guard let input = URL(string: uri), input.isFileURL else { throw ExtractionError.invalidFile }
      let duration = try await AVURLAsset(url: input).load(.duration)
      guard duration.isNumeric, duration.seconds > 0 else { throw ExtractionError.invalidFile }
      return ["duration_ms": Int((duration.seconds * 1000).rounded())]
    }
    AsyncFunction("extract") { (uri: String) async throws -> [String: Any] in
      guard let input = URL(string: uri), input.isFileURL else { throw ExtractionError.invalidFile }
      let directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("extracted-audio", isDirectory: true)
      try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
      let output = directory.appendingPathComponent("\(UUID().uuidString).m4a")
      do { return try await AudioExtractor.extract(input: input, output: output) }
      catch { try? FileManager.default.removeItem(at: output); throw error }
    }
  }
}
