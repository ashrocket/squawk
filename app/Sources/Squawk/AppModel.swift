import Foundation
import SwiftUI

struct Voice: Identifiable, Hashable {
    let id: String      // pool identifier, e.g. "kokoro:af_heart" or "Ava (Premium)"
    let tier: String    // "Default" | "Kokoro" | "Premium" | "Enhanced" | "Basic"

    var label: String {
        if id == "default" { return "System default" }
        if id.hasPrefix("kokoro:") {
            let name = id.split(separator: "_").dropFirst().joined(separator: " ")
            return "Kokoro \(name.capitalized)"
        }
        return id
    }
}

struct InstallStep: Identifiable {
    let id: String
    let title: String
    let detail: String
    let check: (URL) -> Bool
    let installCommand: ((URL) -> String)?   // nil = manual install only
    let manualHint: String?
}

struct ChannelItem: Identifiable, Decodable, Hashable {
    let id: String
    var agent: String?
    var voice: String?
    var session: String?
    var source: String?
    var project: String?
    var priority: Int?
    var status: String?
    var textPreview: String?
    var text: String?
    var answer: String?

    enum CodingKeys: String, CodingKey {
        case id, agent, voice, session, source, project, priority, status, text, answer
        case textPreview = "text_preview"
    }

    var origin: String {
        [project, source, session.map { String($0.prefix(8)) }]
            .compactMap { $0 }.joined(separator: " · ")
    }
}

struct MuxStatus: Decodable {
    var pid: Int?
    var nowPlaying: ChannelItem?
    var queue: [ChannelItem]
    var questions: [ChannelItem]
    var history: [ChannelItem]

    enum CodingKeys: String, CodingKey {
        case pid, queue, questions, history
        case nowPlaying = "now_playing"
    }
}

private struct StatusEnvelope: Decodable {
    var multiplexer: MuxStatus?
}

final class AppModel: ObservableObject {
    @Published var repo: URL?
    @Published var voices: [Voice] = []
    @Published var enabled: Set<String> = []
    @Published var agents: [String: String] = [:]
    @Published var lexicon: [String: String] = [:]
    @Published var log: [String] = []
    @Published var stepStatus: [String: Bool] = [:]
    @Published var busyStep: String?
    @Published var savedFlash = false
    @Published var mux: MuxStatus?
    private var channelTimer: Timer?

    static let kokoroVoices = ["kokoro:af_heart", "kokoro:am_michael", "kokoro:bf_emma",
                               "kokoro:bm_george", "kokoro:af_nicole", "kokoro:am_puck",
                               "kokoro:bf_isabella", "kokoro:bm_lewis"]

    let steps: [InstallStep] = [
        InstallStep(id: "brew", title: "Homebrew", detail: "Package manager",
                    check: { _ in Shell.run("command -v brew").status == 0 },
                    installCommand: nil, manualHint: "Install from https://brew.sh"),
        InstallStep(id: "claude", title: "Claude Code CLI", detail: "The brain",
                    check: { _ in Shell.run("command -v claude").status == 0 },
                    installCommand: nil, manualHint: "Install from https://claude.com/claude-code"),
        InstallStep(id: "whisper", title: "whisper.cpp", detail: "Local speech-to-text (Metal)",
                    check: { _ in Shell.run("brew list whisper-cpp").status == 0 },
                    installCommand: { _ in "brew install whisper-cpp" }, manualHint: nil),
        InstallStep(id: "model", title: "Whisper model", detail: "base.en, ~142 MB",
                    check: { repo in FileManager.default.fileExists(
                        atPath: repo.appendingPathComponent("models/ggml-base.en.bin").path) },
                    installCommand: { _ in
                        "mkdir -p models logs && curl -L -o models/ggml-base.en.bin " +
                        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
                    }, manualHint: nil),
        InstallStep(id: "venv", title: "Python environment", detail: "sounddevice, numpy",
                    check: { repo in FileManager.default.fileExists(
                        atPath: repo.appendingPathComponent(".venv/bin/python3").path) },
                    installCommand: { _ in
                        "python3 -m venv .venv && .venv/bin/pip install --quiet sounddevice numpy"
                    }, manualHint: nil),
        InstallStep(id: "kokoro", title: "Kokoro neural TTS", detail: "8 neural voices, ~340 MB (optional)",
                    check: { repo in FileManager.default.fileExists(
                        atPath: repo.appendingPathComponent("models/kokoro-v1.0.onnx").path) },
                    installCommand: { _ in
                        ".venv/bin/pip install --quiet kokoro-onnx && " +
                        "curl -L -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx && " +
                        "curl -L -o models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
                    }, manualHint: nil),
    ]

    init() {
        repo = Self.locateRepo()
        reload()
    }

    /// The repo is wherever speak.py lives: env override, walk up from the
    /// app bundle (app lives in repo/app/), or the default checkout path.
    static func locateRepo() -> URL? {
        let fm = FileManager.default
        let isRepo = { (u: URL) in fm.fileExists(atPath: u.appendingPathComponent("speak.py").path) }
        if let env = ProcessInfo.processInfo.environment["SQUAWK_REPO"] {
            let u = URL(fileURLWithPath: env)
            if isRepo(u) { return u }
        }
        var probe = Bundle.main.bundleURL.deletingLastPathComponent()
        for _ in 0..<5 {
            if isRepo(probe) { return probe }
            probe.deleteLastPathComponent()
        }
        let fallback = fm.homeDirectoryForCurrentUser.appendingPathComponent("ashcode/squawk")
        return isRepo(fallback) ? fallback : nil
    }

    func reload() {
        guard let repo else { return }
        loadVoices(repo)
        agents = (try? Self.readJSON(repo.appendingPathComponent("voices.json"))) ?? [:]
        lexicon = (try? Self.readJSON(repo.appendingPathComponent("lexicon.json"))) ?? [:]
        refreshChecks()
    }

    func refreshChecks() {
        guard let repo else { return }
        DispatchQueue.global(qos: .userInitiated).async { [steps] in
            var status: [String: Bool] = [:]
            for step in steps { status[step.id] = step.check(repo) }
            DispatchQueue.main.async { self.stepStatus = status }
        }
    }

    private func loadVoices(_ repo: URL) {
        var found: [Voice] = [Voice(id: "default", tier: "Default")]
        let kokoroReady = FileManager.default.fileExists(
            atPath: repo.appendingPathComponent("models/kokoro-v1.0.onnx").path)
        if kokoroReady {
            found += Self.kokoroVoices.map { Voice(id: $0, tier: "Kokoro") }
        }
        let (status, output) = Shell.run("say -v '?'")
        if status == 0 {
            let pattern = try! NSRegularExpression(pattern: "^(.*?)\\s+en[_-][A-Z]{2}\\s+#")
            for line in output.split(separator: "\n") {
                let s = String(line)
                let range = NSRange(s.startIndex..., in: s)
                guard let m = pattern.firstMatch(in: s, range: range),
                      let r = Range(m.range(at: 1), in: s) else { continue }
                let name = s[r].trimmingCharacters(in: .whitespaces)
                guard !found.contains(where: { $0.id == name }) else { continue }
                let tier = name.contains("(Premium)") ? "Premium"
                         : name.contains("(Enhanced)") ? "Enhanced" : "Basic"
                found.append(Voice(id: name, tier: tier))
            }
        }
        voices = found

        let poolFile = repo.appendingPathComponent("pool.json")
        if let data = try? Data(contentsOf: poolFile),
           let chosen = try? JSONDecoder().decode([String].self, from: data) {
            enabled = Set(chosen)
        } else {
            // mirror build_pool()'s computed default: default + kokoro + premium
            enabled = Set(found.filter { ["Default", "Kokoro", "Premium"].contains($0.tier) }.map(\.id))
        }
    }

    /// Pool order is canonical (default, Kokoro, Premium, Enhanced, Basic) filtered to enabled.
    var orderedPool: [String] {
        let rank = ["Default": 0, "Kokoro": 1, "Premium": 2, "Enhanced": 3, "Basic": 4]
        return voices.sorted { (rank[$0.tier] ?? 9, $0.id) < (rank[$1.tier] ?? 9, $1.id) }
            .map(\.id).filter { enabled.contains($0) }
    }

    func save() {
        guard let repo else { return }
        try? Self.writeJSON(orderedPool, to: repo.appendingPathComponent("pool.json"))
        try? Self.writeJSON(agents, to: repo.appendingPathComponent("voices.json"))
        try? Self.writeJSON(lexicon, to: repo.appendingPathComponent("lexicon.json"))
        savedFlash = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.savedFlash = false }
    }

    // MARK: Channel (multiplexer)

    func startChannelPolling() {
        stopChannelPolling()
        pollChannel()
        channelTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            self?.pollChannel()
        }
    }

    func stopChannelPolling() {
        channelTimer?.invalidate()
        channelTimer = nil
    }

    func pollChannel() {
        guard let repo else { return }
        DispatchQueue.global(qos: .utility).async {
            let (status, output) = Shell.run("./speak --status --json", cwd: repo)
            let mux: MuxStatus? = status == 0
                ? (try? JSONDecoder().decode(StatusEnvelope.self, from: Data(output.utf8)))?.multiplexer
                : nil
            DispatchQueue.main.async { self.mux = mux }
        }
    }

    /// Route the user's answer back to the session that asked, via the daemon.
    func sendAnswer(questionID: String, text: String) {
        guard let repo else { return }
        let command = "./speak --answer \(shellQuote(questionID)) \(shellQuote(text))"
        Shell.runStreaming(command, cwd: repo,
                           onLine: { [weak self] in self?.log.append($0) },
                           onExit: { [weak self] _ in self?.pollChannel() })
    }

    func preview(_ voice: String) {
        guard let repo else { return }
        let line = "Hold fast to dreams, for if dreams die, life is a broken-winged bird that cannot fly."
        Shell.runStreaming("./speak --voice \(shellQuote(voice)) \(shellQuote(line))",
                           cwd: repo, onLine: { _ in }, onExit: { _ in })
    }

    func runInstall(_ step: InstallStep) {
        guard let repo, let command = step.installCommand?(repo) else { return }
        busyStep = step.id
        log.append("$ \(command)")
        Shell.runStreaming(command, cwd: repo,
                           onLine: { [weak self] in self?.log.append($0) },
                           onExit: { [weak self] status in
                               self?.log.append(status == 0 ? "done." : "FAILED (exit \(status))")
                               self?.busyStep = nil
                               self?.refreshChecks()
                           })
    }

    private func shellQuote(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    static func readJSON(_ url: URL) throws -> [String: String] {
        try JSONDecoder().decode([String: String].self, from: Data(contentsOf: url))
    }

    static func writeJSON(_ value: some Encodable, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(value).write(to: url)
    }
}
