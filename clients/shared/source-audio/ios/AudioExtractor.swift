import AVFoundation
import Foundation

public enum ExtractionError: Error {
  case invalidFile, missingAudio, reader(String), writer(String), timingGap
}

/// Decoded sample presentation timestamps define the canonical source clock.
public enum AudioExtractor {
  public static func extract(input: URL, output: URL) async throws -> [String: Any] {
    let asset = AVURLAsset(url: input)
    let duration = try await asset.load(.duration)
    guard duration.isNumeric, duration.seconds > 0 else { throw ExtractionError.invalidFile }
    guard let track = try await asset.loadTracks(withMediaType: .audio).first else {
      throw ExtractionError.missingAudio
    }
    let reader = try AVAssetReader(asset: asset)
    let decoded = AVAssetReaderTrackOutput(track: track, outputSettings: [
      AVFormatIDKey: kAudioFormatLinearPCM,
      AVSampleRateKey: 16000,
      AVNumberOfChannelsKey: 1,
      AVLinearPCMBitDepthKey: 16,
      AVLinearPCMIsFloatKey: false,
      AVLinearPCMIsBigEndianKey: false,
      AVLinearPCMIsNonInterleaved: false,
    ])
    decoded.alwaysCopiesSampleData = false
    reader.add(decoded)
    let writer = try AVAssetWriter(outputURL: output, fileType: .m4a)
    let encoded = AVAssetWriterInput(mediaType: .audio, outputSettings: [
      AVFormatIDKey: kAudioFormatMPEG4AAC,
      AVSampleRateKey: 16000,
      AVNumberOfChannelsKey: 1,
      AVEncoderBitRateKey: 48000,
    ])
    writer.add(encoded)
    guard reader.startReading(), writer.startWriting() else {
      throw ExtractionError.reader(reader.error?.localizedDescription ?? "Cannot start media reader")
    }
    guard let first = decoded.copyNextSampleBuffer() else { throw ExtractionError.missingAudio }
    let origin = CMSampleBufferGetPresentationTimeStamp(first)
    writer.startSession(atSourceTime: origin)
    var next: CMSampleBuffer? = first
    var previousEnd = origin
    while let sample = next {
      let pts = CMSampleBufferGetPresentationTimeStamp(sample)
      let sampleDuration = CMSampleBufferGetDuration(sample)
      guard abs((pts - previousEnd).seconds) < 0.025 else {
        reader.cancelReading()
        writer.cancelWriting()
        throw ExtractionError.timingGap
      }
      while !encoded.isReadyForMoreMediaData {
        if writer.status == .failed { throw ExtractionError.writer(writer.error?.localizedDescription ?? "Audio writer failed") }
        try await Task.sleep(nanoseconds: 2_000_000)
      }
      guard encoded.append(sample) else { throw ExtractionError.writer(writer.error?.localizedDescription ?? "Cannot encode audio") }
      previousEnd = pts + sampleDuration
      next = decoded.copyNextSampleBuffer()
    }
    guard reader.status == .completed else { throw ExtractionError.reader(reader.error?.localizedDescription ?? "Audio decode failed") }
    encoded.markAsFinished()
    await writer.finishWriting()
    guard writer.status == .completed else { throw ExtractionError.writer(writer.error?.localizedDescription ?? "Audio encode failed") }
    let resultAsset = AVURLAsset(url: output)
    let resultDuration = try await resultAsset.load(.duration)
    return [
      "uri": output.absoluteString,
      "source_duration_ms": Int((duration.seconds * 1000).rounded()),
      "timing": [
        "media_origin_ms": max(0, Int((origin.seconds * 1000).rounded())),
        "encoder_delay_ms": 0,
        "duration_ms": Int((resultDuration.seconds * 1000).rounded()),
        "sample_rate": 16000,
        "extractor": "avfoundation-aac-16k-v1",
      ],
    ]
  }
}
