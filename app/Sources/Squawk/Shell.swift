import Foundation

enum Shell {
    /// Run a command through a login zsh (so brew etc. are on PATH); blocks.
    @discardableResult
    static func run(_ command: String, cwd: URL? = nil) -> (status: Int32, output: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = ["-lc", command]
        if let cwd { p.currentDirectoryURL = cwd }
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        do { try p.run() } catch { return (-1, "failed to launch: \(error)") }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }

    /// Run a command in the background, streaming lines to the main thread.
    static func runStreaming(_ command: String, cwd: URL? = nil,
                             onLine: @escaping (String) -> Void,
                             onExit: @escaping (Int32) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/zsh")
            p.arguments = ["-lc", command]
            if let cwd { p.currentDirectoryURL = cwd }
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            pipe.fileHandleForReading.readabilityHandler = { handle in
                let data = handle.availableData
                guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
                DispatchQueue.main.async {
                    for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
                        onLine(String(line))
                    }
                }
            }
            do { try p.run() } catch {
                DispatchQueue.main.async {
                    onLine("failed to launch: \(error)")
                    onExit(-1)
                }
                return
            }
            p.waitUntilExit()
            pipe.fileHandleForReading.readabilityHandler = nil
            let status = p.terminationStatus
            DispatchQueue.main.async { onExit(status) }
        }
    }
}
