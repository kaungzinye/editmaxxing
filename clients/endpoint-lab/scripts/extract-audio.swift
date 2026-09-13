import Foundation

@main struct Probe {
  static func main() async throws {
    guard CommandLine.arguments.count == 3 else {
      fatalError("Usage: extract-audio INPUT_VIDEO OUTPUT_M4A")
    }
    let result = try await AudioExtractor.extract(
      input: URL(fileURLWithPath: CommandLine.arguments[1]),
      output: URL(fileURLWithPath: CommandLine.arguments[2]))
    let json = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    print(String(data: json, encoding: .utf8)!)
  }
}
