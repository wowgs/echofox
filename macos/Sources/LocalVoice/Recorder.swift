// The microphone, converted to what the server takes: 16 kHz, 16-bit little-endian PCM, mono.
import AVFoundation

final class Recorder {
    static let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
    private let engine = AVAudioEngine()
    private var running = false

    /// Starts the microphone; `onPCM` gets each converted buffer, on an audio thread.
    func start(onPCM: @escaping (Data) -> Void) throws {
        let input = engine.inputNode
        let from = input.outputFormat(forBus: 0)
        guard from.sampleRate > 0, from.channelCount > 0 else {
            throw NSError(domain: "LocalVoice", code: 2, userInfo: [NSLocalizedDescriptionKey: "no microphone input"])
        }
        guard let converter = AVAudioConverter(from: from, to: Recorder.format) else {
            throw NSError(domain: "LocalVoice", code: 3, userInfo: [NSLocalizedDescriptionKey: "cannot convert \(from) to 16 kHz"])
        }
        input.installTap(onBus: 0, bufferSize: 4096, format: from) { buffer, _ in
            let capacity = AVAudioFrameCount(Double(buffer.frameLength) * 16000 / from.sampleRate) + 64
            guard let out = AVAudioPCMBuffer(pcmFormat: Recorder.format, frameCapacity: capacity) else { return }
            var given = false
            var error: NSError?
            // .noDataNow, not .endOfStream: the converter keeps its resampling state between buffers.
            converter.convert(to: out, error: &error) { _, status in
                if given {
                    status.pointee = .noDataNow
                    return nil
                }
                given = true
                status.pointee = .haveData
                return buffer
            }
            if error == nil, out.frameLength > 0, let samples = out.int16ChannelData {
                onPCM(Data(bytes: samples[0], count: Int(out.frameLength) * 2))
            }
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            throw error
        }
        running = true
    }

    func stop() {
        guard running else { return }
        running = false
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}
