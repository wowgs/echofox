// The microphone, converted to what the server takes: 16-bit little-endian PCM, mono, at the server's sample rate.
// When the input device changes during a recording (AirPods connected or gone), AVAudioEngine stops and posts
// AVAudioEngineConfigurationChange; the recorder then starts again on the new device, and says so if it cannot. With a
// `device`, the engine's input is that microphone (kAudioOutputUnitProperty_CurrentDevice) when it is not macOS's input
// already, so a headset that connects does not take the recording over.
import AudioToolbox
import AVFoundation
import LocalVoiceCore

final class Recorder {
    private let engine = AVAudioEngine()
    private let format: AVAudioFormat
    private var running = false
    private var onPCM: (Data) -> Void = { _ in }
    private var onLost: (String) -> Void = { _ in }
    private var observer: NSObjectProtocol?

    private let device: AudioDeviceID?

    /// `device`: the microphone to record (nil: macOS's input).
    init(sampleRate: Double, device: AudioDeviceID? = nil) {
        format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: 1, interleaved: true)!
        self.device = device
    }

    /// Starts the microphone; `onPCM` gets each converted buffer (on an audio thread), `onLost` why the microphone
    /// stopped for good.
    func start(onPCM: @escaping (Data) -> Void, onLost: @escaping (String) -> Void) throws {
        self.onPCM = onPCM
        self.onLost = onLost
        try tap()
        observer = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine,
                                                          queue: .main) { [weak self] _ in self?.deviceChanged() }
        running = true
    }

    private func tap() throws {
        let input = engine.inputNode
        // Setting the device makes AVAudioEngine post a configuration change, after which the restarted engine gave no
        // audio (2026-10-18, two recordings of 0.0 s). So the device is set only when it is not macOS's input already.
        if var id = device, id != AudioInputs.defaultInput() {
            guard let unit = input.audioUnit else { throw MessageError("the audio input has no audio unit") }
            let status = AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0,
                                              &id, UInt32(MemoryLayout<AudioDeviceID>.size))
            guard status == noErr else { throw MessageError("cannot record the chosen microphone (status \(status))") }
        }
        let from = input.outputFormat(forBus: 0)
        guard from.sampleRate > 0, from.channelCount > 0 else { throw MessageError("no microphone input") }
        guard let converter = AVAudioConverter(from: from, to: format) else {
            throw MessageError("cannot convert \(from) to \(format.sampleRate) Hz")
        }
        let out = format, emit = onPCM
        input.installTap(onBus: 0, bufferSize: Tuning.recorderBufferFrames, format: from) { buffer, _ in
            let ratio = out.sampleRate / from.sampleRate
            let capacity = AVAudioFrameCount((Double(buffer.frameLength) * ratio).rounded(.up)) + 1
            guard let converted = AVAudioPCMBuffer(pcmFormat: out, frameCapacity: capacity) else { return }
            var given = false
            var error: NSError?
            // .noDataNow, not .endOfStream: the converter keeps its resampling state between buffers.
            converter.convert(to: converted, error: &error) { _, status in
                if given {
                    status.pointee = .noDataNow
                    return nil
                }
                given = true
                status.pointee = .haveData
                return buffer
            }
            if error == nil, converted.frameLength > 0, let samples = converted.int16ChannelData {
                emit(Data(bytes: samples[0], count: Int(converted.frameLength) * MemoryLayout<Int16>.size))
            }
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            throw error
        }
    }

    private func deviceChanged() {
        guard running else { return }
        Log.write("the audio input changed: the microphone starts again")
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        do {
            try tap()
        } catch {
            stop()
            onLost(error.localizedDescription)
        }
    }

    func stop() {
        guard running else { return }
        running = false
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = nil
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}
