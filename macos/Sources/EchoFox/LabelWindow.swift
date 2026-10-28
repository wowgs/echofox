// The labeling window: one card for each piece not labeled yet (EchoFoxCore/Labeling.swift). The piece plays at
// once; you correct the model's text into what you meant to write (Labeling.convention), and go on, until you stop
// or the pieces end. It opens in the lower right corner of the screen, a third of its width and a
// bit under half its height; its frame, once moved or resized, is kept.
import AppKit
import AVFoundation
import EchoFoxCore
import SwiftUI

final class LabelWindow: NSObject, NSWindowDelegate {
    private var window: NSWindow?
    private var model: LabelModel?

    func show(recordings: URL, labeled: URL) {
        if let window {
            MainMenu.bringForward(window)
            return
        }
        let model = LabelModel(recordings: recordings, labeled: labeled)
        model.onStop = { [weak self] in self?.window?.close() }
        let w = NSWindow(contentRect: Self.corner(), styleMask: [.titled, .closable, .resizable, .fullSizeContentView],
                         backing: .buffered, defer: false)
        w.title = "Label Recordings"
        w.titlebarAppearsTransparent = true
        w.isReleasedWhenClosed = false
        w.minSize = NSSize(width: Tuning.labelWindowMinWidth, height: Tuning.labelWindowMinHeight)
        w.contentView = NSHostingView(rootView: LabelView(model: model))
        w.setFrameAutosaveName("LabelRecordings")  // a frame the user chose wins over the corner
        w.delegate = self
        self.window = w
        self.model = model
        MainMenu.bringForward(w)
        model.load()
    }

    /// The lower right corner of the screen with the mouse.
    private static func corner() -> NSRect {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) } ?? NSScreen.main
        let area = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let w = max(Tuning.labelWindowMinWidth, area.width * Tuning.labelWindowWidthShare)
        let h = max(Tuning.labelWindowMinHeight, area.height * Tuning.labelWindowHeightShare)
        let m = Tuning.labelWindowMargin
        return NSRect(x: area.maxX - w - m, y: area.minY + m, width: w, height: h)
    }

    func windowWillClose(_ notification: Notification) {
        model?.stopAudio()
        model = nil
        window = nil
    }
}

final class LabelModel: ObservableObject {
    @Published var items: [LabelItem] = []
    @Published var index = 0
    @Published var text = ""
    @Published var loading = true
    @Published var error: String?
    @Published var playing = false
    @Published var progress = 0.0
    @Published var saved = 0
    var onStop: () -> Void = {}

    private let recordings: URL, labeled: URL
    private var player: AVAudioPlayer?
    private var timer: Timer?

    init(recordings: URL, labeled: URL) {
        self.recordings = recordings
        self.labeled = labeled
    }

    var current: LabelItem? { index < items.count ? items[index] : nil }

    func load() {
        let recordings = self.recordings, labeled = self.labeled
        DispatchQueue.global(qos: .userInitiated).async {
            // In random order, not the newest first: the labels then come from every day and every kind of
            // dictation, and the days held out for checking a trained model have labels too.
            let items = Labeling.pending(recordings: recordings, labeled: labeled).shuffled()
            DispatchQueue.main.async {
                self.items = items
                self.loading = false
                self.open(0)
            }
        }
    }

    private func open(_ i: Int) {
        index = i
        error = nil
        stopAudio()
        guard let item = current else { return }
        text = item.text  // the text that went into the input box: the hesitation sounds are already out
        play()
    }

    func play() {
        guard let item = current else { return }
        stopAudio()
        do {
            let p = try AVAudioPlayer(contentsOf: item.audio)
            p.play()
            player = p
            playing = true
            timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in self?.tick() }
        } catch {
            self.error = "cannot play \(item.audio.lastPathComponent): \(error.localizedDescription)"
        }
    }

    func togglePlay() {
        if let p = player, p.isPlaying {
            p.pause()
            playing = false
        } else if let p = player, p.currentTime > 0 {
            p.play()
            playing = true
        } else {
            play()
        }
    }

    private func tick() {
        guard let p = player else { return }
        progress = p.duration > 0 ? p.currentTime / p.duration : 0
        if !p.isPlaying, playing {
            playing = false
            if p.currentTime == 0 { progress = 1 }
        }
    }

    func stopAudio() {
        timer?.invalidate()
        timer = nil
        player?.stop()
        player = nil
        playing = false
        progress = 0
    }

    func save(_ status: LabelStatus) {
        guard let item = current else { return }
        do {
            try Labeling.save(item, text: text, status: status, labeled: labeled)
            saved += 1
            Log.write("labeled \(item.recording) piece \(item.piece): \(status.rawValue), \(text.count) characters")
            open(index + 1)
        } catch {
            self.error = "cannot save: \(error.localizedDescription)"
        }
    }

    func later() { open(index + 1) }

    func stop() {
        stopAudio()
        onStop()
    }
}

struct LabelView: View {
    @ObservedObject var model: LabelModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if model.loading {
                Spacer()
                ProgressView("Looking for recordings…").frame(maxWidth: .infinity)
                Spacer()
            } else if let item = model.current {
                card(item)
            } else {
                done
            }
        }
        .padding(.horizontal, 22)
        .padding(.top, 34)
        .padding(.bottom, 18)
        .frame(minWidth: Tuning.labelWindowMinWidth - 44, minHeight: Tuning.labelWindowMinHeight - 52)
    }

    private func card(_ item: LabelItem) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.place ?? "No chat context").font(.headline).lineLimit(1)
                    Text(subtitle(item)).font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                Text("\(model.items.count - model.index) left").font(.subheadline).foregroundStyle(.secondary)
            }
            HStack(spacing: 12) {
                Button(action: model.togglePlay) {
                    Image(systemName: model.playing ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 30))
                }
                .buttonStyle(.plain)
                .help(model.playing ? "Pause" : "Play")
                ProgressView(value: model.progress).progressViewStyle(.linear)
                Button("Play Again", action: model.play).keyboardShortcut("r", modifiers: .command)
            }
            TextEditor(text: $model.text)
                .font(.system(size: 15))
                .inputBox(cornerRadius: 8)
            Text("Write what you meant to write: no э, мм, а-а, no repeats; after a slip, only what you corrected it to.")
                .font(.caption).foregroundStyle(.secondary)
            if let e = model.error { Text(e).font(.caption).foregroundStyle(.red) }
            HStack {
                Button("Unusable", action: { model.save(.unusable) }).keyboardShortcut("u", modifiers: .command)
                    .help("Not your voice, a TV, noise: kept, but no example (⌘U)")
                Button("Later", action: model.later).keyboardShortcut("l", modifiers: .command)
                    .help("Not now; it comes back next time (⌘L)")
                Spacer()
                Button("Stop", action: model.stop).keyboardShortcut(.cancelAction)
                Button("Save and Next", action: { model.save(.verified) })
                    .keyboardShortcut(.return, modifiers: .command)
                    .buttonStyle(.borderedProminent)
                    .help("The text is what you said (⌘↩)")
            }
        }
    }

    private var done: some View {
        VStack(spacing: 10) {
            Spacer()
            Image(systemName: "checkmark.circle").font(.system(size: 40)).foregroundStyle(.secondary)
            Text(model.items.isEmpty ? "Nothing to label." : "All pieces are labeled.").font(.headline)
            Text("Saved this time: \(model.saved)").foregroundStyle(.secondary)
            Button("Close", action: model.stop).keyboardShortcut(.cancelAction)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private func subtitle(_ item: LabelItem) -> String {
        var parts = [String]()
        if let s = item.started { parts.append(Self.date(s)) }
        parts.append("piece \(item.piece)")
        if let s = item.audioSeconds { parts.append(String(format: "%.1f s", s)) }
        return parts.joined(separator: " · ")
    }

    private static func date(_ iso: String) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let d = f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else { return iso }
        return d.formatted(date: .abbreviated, time: .shortened)
    }
}
