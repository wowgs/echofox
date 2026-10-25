// The microphone, converted to what the server takes: 16-bit little-endian PCM, mono, at the server's sample rate.
//
// The recorder has an input audio unit of its own (AUHAL: kAudioUnitSubType_HALOutput, input on, output off), bound
// to one device before the unit is initialized. So the app records the microphone it chose, whatever macOS's input is
// and whatever connects meanwhile. An earlier version set the device on AVAudioEngine's input node instead; the engine
// then reconfigured itself, posted a configuration change 50–70 ms after the start, and the restart that followed gave
// no audio (2026-10-18, two recordings of 0.0 s). The unit hands the device's audio as 32-bit floats at the device's
// rate, and the input callback converts it (AVAudioConverter). If the device goes away during a recording
// (kAudioDevicePropertyDeviceIsAlive), the recorder stops and says so.
import AudioToolbox
import AVFoundation
import CoreAudio
import EchoFoxCore

final class Recorder {
    private let format: AVAudioFormat
    private let device: AudioDeviceID?
    private var unit: AudioUnit?
    private var bound: AudioDeviceID = 0
    private var converter: AVAudioConverter?
    private var buffer: AVAudioPCMBuffer?
    private var render: UnsafeMutablePointer<Float>?  // what the unit renders into, interleaved
    private var channels = 1
    private var onPCM: (Data) -> Void = { _ in }
    private var onLost: (String) -> Void = { _ in }
    private var aliveListener: AudioObjectPropertyListenerBlock?
    private var running = false
    /// What the input callback saw, for the recorder's check (RecordTest): calls, failed renders and the last status,
    /// failed conversions. Written on the audio thread, read after stop().
    private(set) var stats = (calls: 0, renderErrors: 0, lastStatus: OSStatus(0), convertErrors: 0, tooLong: 0)
    private(set) var formats = ""

    /// `device`: the microphone to record; nil: macOS's input at the start.
    init(sampleRate: Double, device: AudioDeviceID? = nil) {
        format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: 1, interleaved: true)!
        self.device = device
    }

    /// Starts the microphone; `onPCM` gets each converted buffer (on an audio thread), `onLost` why the microphone
    /// stopped for good.
    func start(onPCM: @escaping (Data) -> Void, onLost: @escaping (String) -> Void) throws {
        self.onPCM = onPCM
        self.onLost = onLost
        guard let id = device ?? AudioInputs.defaultInput() else { throw MessageError("no microphone") }
        do {
            try open(id)
        } catch {
            close()
            throw error
        }
        bound = id
        running = true
        watch(id)
    }

    func stop() {
        guard running else { return }
        running = false
        unwatch()
        close()
    }

    // MARK: The unit

    private func open(_ id: AudioDeviceID) throws {
        var desc = AudioComponentDescription(componentType: kAudioUnitType_Output,
                                             componentSubType: kAudioUnitSubType_HALOutput,
                                             componentManufacturer: kAudioUnitManufacturer_Apple,
                                             componentFlags: 0, componentFlagsMask: 0)
        guard let component = AudioComponentFindNext(nil, &desc) else { throw MessageError("no audio input unit") }
        var made: AudioUnit?
        try check(AudioComponentInstanceNew(component, &made), "create the audio input unit")
        guard let u = made else { throw MessageError("no audio input unit") }
        unit = u
        var on: UInt32 = 1, off: UInt32 = 0
        try set(u, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Input, 1, &on, "turn the input on")
        try set(u, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Output, 0, &off, "turn the output off")
        var device = id
        try set(u, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &device, "choose the microphone")
        // The device's own format is the input scope of bus 1; the app takes it on the output scope of bus 1.
        var hardware = AudioStreamBasicDescription()
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        try check(AudioUnitGetProperty(u, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 1, &hardware, &size),
                  "read the microphone's format")
        guard hardware.mSampleRate > 0, hardware.mChannelsPerFrame > 0 else { throw MessageError("no microphone input") }
        guard let client = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: hardware.mSampleRate,
                                         channels: hardware.mChannelsPerFrame, interleaved: true) else {
            throw MessageError("the microphone's format is not usable")
        }
        var clientDescription = client.streamDescription.pointee
        try set(u, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 1, &clientDescription, "set the format")
        var now = AudioStreamBasicDescription()
        size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        _ = AudioUnitGetProperty(u, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 1, &now, &size)
        func show(_ d: AudioStreamBasicDescription) -> String {
            "\(d.mSampleRate) Hz, \(d.mChannelsPerFrame) ch, \(d.mBitsPerChannel) bit, flags \(d.mFormatFlags), \(d.mBytesPerFrame) B/frame"
        }
        formats = "device: \(show(hardware)); asked: \(show(clientDescription)); unit now: \(show(now))"
        guard let c = AVAudioConverter(from: client, to: format) else {
            throw MessageError("cannot convert \(client) to \(format.sampleRate) Hz")
        }
        c.downmix = true  // a device with several channels gives one
        converter = c
        var maxFrames: UInt32 = 4096
        size = UInt32(MemoryLayout<UInt32>.size)
        _ = AudioUnitGetProperty(u, kAudioUnitProperty_MaximumFramesPerSlice, kAudioUnitScope_Global, 0, &maxFrames, &size)
        let capacity = max(maxFrames, Tuning.recorderBufferFrames)
        buffer = AVAudioPCMBuffer(pcmFormat: client, frameCapacity: capacity)
        channels = Int(hardware.mChannelsPerFrame)
        render = UnsafeMutablePointer<Float>.allocate(capacity: Int(capacity) * channels)
        formats += "; buffers \(buffer.map { UnsafeMutableAudioBufferListPointer($0.mutableAudioBufferList).count } ?? -1), max frames \(maxFrames)"
        var callback = AURenderCallbackStruct(inputProc: { refCon, flags, time, bus, frames, _ in
            Unmanaged<Recorder>.fromOpaque(refCon).takeUnretainedValue().input(flags, time, bus, frames)
        }, inputProcRefCon: Unmanaged.passUnretained(self).toOpaque())
        try set(u, kAudioOutputUnitProperty_SetInputCallback, kAudioUnitScope_Global, 0, &callback, "set the callback")
        try check(AudioUnitInitialize(u), "start the audio input unit")
        try check(AudioOutputUnitStart(u), "start the microphone")
    }

    private func close() {
        guard let u = unit else { return }
        AudioOutputUnitStop(u)
        AudioUnitUninitialize(u)
        AudioComponentInstanceDispose(u)
        unit = nil
        render?.deallocate()
        render = nil
    }

    /// The input callback, on the audio thread: the device's frames → the server's format.
    private func input(_ flags: UnsafeMutablePointer<AudioUnitRenderActionFlags>, _ time: UnsafePointer<AudioTimeStamp>,
                       _ bus: UInt32, _ frames: UInt32) -> OSStatus {
        stats.calls += 1
        guard let u = unit, let buffer, let converter else { return noErr }
        guard frames <= buffer.frameCapacity, let render else { stats.tooLong += 1; return noErr }
        // A buffer list of our own over our own memory, as AUHAL wants it for an input render; a buffer list that
        // belongs to an AVAudioPCMBuffer was refused with -50 (kAudio_ParamError) on every call (2026-10-18).
        let bytes = frames * UInt32(channels * MemoryLayout<Float>.size)
        var list = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: UInt32(channels),
                                                                             mDataByteSize: bytes, mData: render))
        let status = AudioUnitRender(u, flags, time, bus, frames, &list)
        guard status == noErr else {
            stats.renderErrors += 1
            stats.lastStatus = status
            return status
        }
        guard let target = buffer.floatChannelData?[0] else { return noErr }
        target.update(from: render, count: Int(frames) * channels)
        buffer.frameLength = frames
        let ratio = format.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount((Double(frames) * ratio).rounded(.up)) + 1
        guard let converted = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return noErr }
        var given = false
        var error: NSError?
        // .noDataNow, not .endOfStream: the converter keeps its resampling state between buffers.
        converter.convert(to: converted, error: &error) { _, state in
            if given {
                state.pointee = .noDataNow
                return nil
            }
            given = true
            state.pointee = .haveData
            return buffer
        }
        if error != nil { stats.convertErrors += 1 }
        if error == nil, converted.frameLength > 0, let samples = converted.int16ChannelData {
            onPCM(Data(bytes: samples[0], count: Int(converted.frameLength) * MemoryLayout<Int16>.size))
        }
        return noErr
    }

    // MARK: The device going away

    private func watch(_ id: AudioDeviceID) {
        var address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDeviceIsAlive,
                                                 mScope: kAudioObjectPropertyScopeGlobal,
                                                 mElement: kAudioObjectPropertyElementMain)
        let listener: AudioObjectPropertyListenerBlock = { [weak self] _, _ in
            DispatchQueue.main.async {
                guard let self, self.running, !Self.alive(id) else { return }
                self.stop()
                self.onLost("the microphone was disconnected")
            }
        }
        if AudioObjectAddPropertyListenerBlock(id, &address, DispatchQueue.main, listener) == noErr {
            aliveListener = listener
        }
    }

    private func unwatch() {
        guard let listener = aliveListener else { return }
        var address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDeviceIsAlive,
                                                 mScope: kAudioObjectPropertyScopeGlobal,
                                                 mElement: kAudioObjectPropertyElementMain)
        AudioObjectRemovePropertyListenerBlock(bound, &address, DispatchQueue.main, listener)
        aliveListener = nil
    }

    private static func alive(_ id: AudioDeviceID) -> Bool {
        var address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDeviceIsAlive,
                                                 mScope: kAudioObjectPropertyScopeGlobal,
                                                 mElement: kAudioObjectPropertyElementMain)
        var value: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        return AudioObjectGetPropertyData(id, &address, 0, nil, &size, &value) == noErr && value != 0
    }

    // MARK: Helpers

    private func check(_ status: OSStatus, _ what: String) throws {
        guard status == noErr else { throw MessageError("cannot \(what) (status \(status))") }
    }

    private func set<T>(_ u: AudioUnit, _ property: AudioUnitPropertyID, _ scope: AudioUnitScope,
                        _ element: AudioUnitElement, _ value: inout T, _ what: String) throws {
        let status = withUnsafePointer(to: &value) {
            AudioUnitSetProperty(u, property, scope, element, UnsafeRawPointer($0), UInt32(MemoryLayout<T>.size))
        }
        try check(status, what)
    }
}
