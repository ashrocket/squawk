import SwiftUI

/// Live view of the multiplexer: what's playing, what's queued, and pending
/// questions. Answers typed here route back to the exact session that asked.
struct ChannelView: View {
    @ObservedObject var model: AppModel
    @State private var answers: [String: String] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let mux = model.mux {
                Text("Traffic cop running (pid \(mux.pid.map(String.init) ?? "?")). One voice at a time; urgent jumps the queue.")
                    .font(.caption).foregroundStyle(.secondary)
                List {
                    if let playing = mux.nowPlaying {
                        Section("Now playing") {
                            row(playing, icon: "speaker.wave.2.fill", tint: .green)
                        }
                    }
                    if !mux.questions.isEmpty {
                        Section("Questions — your answer goes back to the session that asked") {
                            ForEach(mux.questions) { question in
                                questionRow(question)
                            }
                        }
                    }
                    if !mux.queue.isEmpty {
                        Section("Queued (\(mux.queue.count))") {
                            ForEach(mux.queue) { item in
                                row(item, icon: (item.priority ?? 0) > 0
                                    ? "exclamationmark.circle.fill" : "clock",
                                    tint: (item.priority ?? 0) > 0 ? .orange : .secondary)
                            }
                        }
                    }
                    if !mux.history.isEmpty {
                        Section("Recent") {
                            ForEach(mux.history.reversed()) { item in
                                row(item, icon: item.status == "answered"
                                    ? "checkmark.bubble" : "checkmark",
                                    tint: .secondary)
                            }
                        }
                    }
                }
            } else {
                Spacer()
                VStack(spacing: 6) {
                    Image(systemName: "antenna.radiowaves.left.and.right.slash")
                        .font(.largeTitle).foregroundStyle(.secondary)
                    Text("Multiplexer idle").font(.title3)
                    Text("The traffic-cop daemon starts with the first `speak` and exits when idle. Messages will appear here live.")
                        .font(.caption).foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                Spacer()
            }
        }
        .padding()
        .onAppear { model.startChannelPolling() }
        .onDisappear { model.stopChannelPolling() }
    }

    private func row(_ item: ChannelItem, icon: String, tint: Color) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Image(systemName: icon).foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.answer.map { "\(item.textPreview ?? "") — \($0)" }
                     ?? (item.textPreview ?? ""))
                HStack(spacing: 6) {
                    Text(item.agent ?? "?").bold()
                    if let voice = item.voice { Text(voice) }
                    if !item.origin.isEmpty { Text(item.origin) }
                }
                .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    private func questionRow(_ question: ChannelItem) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(question.text ?? question.textPreview ?? "").bold()
            HStack(spacing: 6) {
                Text(question.agent ?? "?")
                if !question.origin.isEmpty { Text(question.origin) }
            }
            .font(.caption).foregroundStyle(.secondary)
            HStack {
                TextField("Type your answer…", text: answerBinding(question.id))
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { submit(question.id) }
                Button("Answer") { submit(question.id) }
                    .disabled((answers[question.id] ?? "").trimmingCharacters(
                        in: .whitespaces).isEmpty)
            }
        }
        .padding(.vertical, 4)
    }

    private func answerBinding(_ id: String) -> Binding<String> {
        Binding(get: { answers[id] ?? "" }, set: { answers[id] = $0 })
    }

    private func submit(_ id: String) {
        let text = (answers[id] ?? "").trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        model.sendAnswer(questionID: id, text: text)
        answers[id] = nil
    }
}
