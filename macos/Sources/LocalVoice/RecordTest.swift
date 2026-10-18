// The recorder's check (main.swift, --record-test): what the chosen microphone gives in a few seconds.
import Foundation
import LocalVoiceCore

enum RecordTest {
    /// `choice`: a microphone choice instead of the config's ("builtin", "system", a device's UID).
    static func run(seconds: Double, out: String, choice: String? = nil) -> Never {
        let config = Config.load()
        let (input, why) = AudioInputs.chosen(choice ?? config.microphone)
        let lock = NSLock()
        var samples = 0, peak: Int16 = 0, callbacks = 0
        let recorder = Recorder(sampleRate: Double(Tuning.defaultSampleRate), device: input?.id)
        var result: [String: Any] = ["microphone": input?.name ?? "macOS's input", "why": why,
                                     "choice": choice ?? config.microphone,
                                     "inputs": AudioInputs.all().map { "\($0.name) [\($0.uid)]\($0.builtIn ? " built-in" : "")" }]
        do {
            try recorder.start(onPCM: { data in
                lock.lock(); defer { lock.unlock() }
                callbacks += 1
                data.withUnsafeBytes { raw in
                    for s in raw.bindMemory(to: Int16.self) {
                        samples += 1
                        peak = max(peak, s == Int16.min ? Int16.max : abs(s))
                    }
                }
            }, onLost: { why in result["lost"] = why })
            Thread.sleep(forTimeInterval: seconds)
            recorder.stop()
        } catch {
            result["error"] = "\(error)"
        }
        if let device = input?.id ?? AudioInputs.defaultInput(), let v = AudioInputs.volume(device) {
            result["inputVolume"] = v
            result["inputVolumeSetsBack"] = AudioInputs.setVolume(v, of: device)  // the same value: nothing changes
        }
        let st = recorder.stats
        result["formats"] = recorder.formats
        result["unit"] = ["calls": st.calls, "renderErrors": st.renderErrors, "lastStatus": Int(st.lastStatus),
                          "convertErrors": st.convertErrors, "tooLong": st.tooLong]
        lock.lock()
        result["callbacks"] = callbacks
        result["samples"] = samples
        result["seconds"] = Double(samples) / Double(Tuning.defaultSampleRate)
        result["peakDbfs"] = peak > 0 ? 20 * log10(Double(peak) / 32767) : -120
        lock.unlock()
        let data = (try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])) ?? Data()
        try? data.write(to: URL(fileURLWithPath: out))
        exit(0)
    }
}
