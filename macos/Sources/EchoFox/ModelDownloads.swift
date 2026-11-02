// The downloads and removals of model variants that this app starts (ModelJob), by variant: one owner, so that the
// first-start window and the settings window show the same job, a second window never starts a second download of a
// variant that downloads, and the uninstall's removals show as removals too. The server's info is asked when a job
// begins to run and when it ends, so that it says whether the variant downloads or is there (not for the uninstall's
// removals: removeForUninstall).
import Combine
import EchoFoxCore
import Foundation

final class ModelDownloads: ObservableObject {
    @Published private(set) var jobs: [String: ModelJob] = [:]
    var askServer: () -> Void = {}
    private var ended: [(_ variant: String, _ job: ModelJob, _ isDownload: Bool) -> Void] = []

    /// `f(variant, job, isDownload)` runs when a job ends, done or failed; `isDownload`: a download, not a removal.
    func onEnd(_ f: @escaping (_ variant: String, _ job: ModelJob, _ isDownload: Bool) -> Void) { ended.append(f) }

    /// The variant's job that runs now, or nil.
    func running(_ variant: String) -> ModelJob? {
        jobs[variant].flatMap { $0.finished ? nil : $0 }
    }

    /// The variant's download: the one that runs, or a new one.
    @discardableResult
    func download(catalog: String, variant: String, url: URL) -> ModelJob {
        if let job = running(variant) { return job }
        return run(variant, ModelJob(url: url, message: ClientMessage.download(catalog: catalog, variant: variant)),
                   isDownload: true)
    }

    func remove(catalog: String, variant: String, url: URL) {
        guard running(variant) == nil else { return }
        run(variant, ModelJob(url: url, message: ClientMessage.remove(catalog: catalog, variant: variant)), isDownload: false)
    }

    func cancel(_ variant: String) { running(variant)?.cancel() }

    /// The removals of an uninstall (Uninstaller), one after another in the order of `variants`; then `done`, also
    /// when one fails (its files stay, said in the log). They ask the server nothing and call no end hook: the app
    /// quits after them, and the first start's window must not open meanwhile.
    func removeForUninstall(catalog: String, variants: [String], url: URL, done: @escaping () -> Void) {
        guard let variant = variants.first else { return done() }
        let job = ModelJob(url: url, message: ClientMessage.remove(catalog: catalog, variant: variant))
        job.onChange = { [weak self, weak job] in
            guard let self, let job else { return }
            self.objectWillChange.send()
            guard job.finished else { return }
            if let e = job.error { Log.write("uninstall: \(variant) not removed: \(e)") }
            self.removeForUninstall(catalog: catalog, variants: Array(variants.dropFirst()), url: url, done: done)
        }
        jobs[variant] = job
        job.start()
    }

    @discardableResult
    private func run(_ variant: String, _ job: ModelJob, isDownload: Bool) -> ModelJob {
        var began = false
        job.onChange = { [weak self, weak job] in
            guard let self, let job else { return }
            self.objectWillChange.send()
            if !job.finished, !began {
                began = true
                self.askServer()
            }
            if job.finished {
                self.askServer()
                self.ended.forEach { $0(variant, job, isDownload) }
            }
        }
        jobs[variant] = job
        job.start()
        return job
    }
}
