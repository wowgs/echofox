// The Mac's audio inputs, through Core Audio, and the one the config's "microphone" names: "builtin" (the default: the
// Mac's own microphone, whatever macOS's input is), "system" (macOS's input, which follows headsets as they come and
// go), or a device's UID (one microphone, kept when others connect).
import CoreAudio
import Foundation
import LocalVoiceCore

struct AudioInput: Equatable {
    let id: AudioDeviceID
    let uid: String
    let name: String
    let builtIn: Bool
}

enum AudioInputs {
    /// Every device with input channels.
    static func all() -> [AudioInput] {
        var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
                                                 mScope: kAudioObjectPropertyScopeGlobal,
                                                 mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        let system = AudioObjectID(kAudioObjectSystemObject)
        guard AudioObjectGetPropertyDataSize(system, &address, 0, nil, &size) == noErr else { return [] }
        var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(system, &address, 0, nil, &size, &ids) == noErr else { return [] }
        return ids.compactMap { id in
            guard inputChannels(id) > 0, let uid = string(id, kAudioDevicePropertyDeviceUID) else { return nil }
            return AudioInput(id: id, uid: uid, name: string(id, kAudioObjectPropertyName) ?? uid,
                              builtIn: transport(id) == kAudioDeviceTransportTypeBuiltIn)
        }
    }

    /// macOS's input device now.
    static func defaultInput() -> AudioDeviceID? {
        var a = address(kAudioHardwarePropertyDefaultInputDevice)
        var id = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        return AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &size, &id) == noErr
            && id != 0 ? id : nil
    }

    /// The device the config's choice names, or nil for macOS's input. A device that is gone falls back to the
    /// built-in microphone, then to macOS's input; `why` says which.
    static func chosen(_ choice: String) -> (input: AudioInput?, why: String) {
        let inputs = all()
        let builtIn = inputs.first(where: \.builtIn)
        switch choice {
        case Config.systemMicrophone:
            return (nil, "macOS's input")
        case Config.builtInMicrophone:
            return builtIn.map { ($0, "the built-in microphone") } ?? (nil, "no built-in microphone: macOS's input")
        default:
            if let device = inputs.first(where: { $0.uid == choice }) { return (device, "the chosen microphone") }
            return builtIn.map { ($0, "the chosen microphone is gone: the built-in one") }
                ?? (nil, "the chosen microphone is gone: macOS's input")
        }
    }

    private static func address(_ selector: AudioObjectPropertySelector,
                                _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal)
        -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    }

    private static func string(_ id: AudioDeviceID, _ selector: AudioObjectPropertySelector) -> String? {
        var a = address(selector)
        var value: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr, let v = value else { return nil }
        return v.takeRetainedValue() as String
    }

    private static func transport(_ id: AudioDeviceID) -> UInt32 {
        var a = address(kAudioDevicePropertyTransportType)
        var value: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        return AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr ? value : 0
    }

    private static func inputChannels(_ id: AudioDeviceID) -> Int {
        var a = address(kAudioDevicePropertyStreamConfiguration, kAudioObjectPropertyScopeInput)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(id, &a, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        let list = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
        guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, list) == noErr else { return 0 }
        return UnsafeMutableAudioBufferListPointer(list).reduce(0) { $0 + Int($1.mNumberChannels) }
    }
}
