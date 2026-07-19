import SwiftUI

struct InstallView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Fixed set of checks: natural height, never scrolls or clips.
            VStack(spacing: 0) {
                ForEach(model.steps) { step in
                    HStack {
                        Image(systemName: model.stepStatus[step.id] == true
                              ? "checkmark.circle.fill" : "circle.dashed")
                            .foregroundStyle(model.stepStatus[step.id] == true ? .green : .secondary)
                        VStack(alignment: .leading) {
                            Text(step.title).font(.headline)
                            Text(step.detail).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if model.stepStatus[step.id] != true {
                            if step.installCommand != nil {
                                Button(model.busyStep == step.id ? "Installing…" : "Install") {
                                    model.runInstall(step)
                                }
                                .disabled(model.busyStep != nil)
                            } else if let hint = step.manualHint {
                                Text(hint).font(.caption).foregroundStyle(.orange)
                            }
                        }
                    }
                    .padding(.vertical, 6)
                    if step.id != model.steps.last?.id { Divider() }
                }
            }
            .padding(.horizontal, 8)
            // The log takes whatever space is left below the checks.
            GroupBox("Log") {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 1) {
                            ForEach(Array(model.log.enumerated()), id: \.offset) { i, line in
                                Text(line).font(.system(.caption, design: .monospaced)).id(i)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .onChange(of: model.log.count) {
                        proxy.scrollTo(model.log.count - 1, anchor: .bottom)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .frame(maxHeight: .infinity)
            HStack {
                Button("Refresh Status") { model.refreshChecks() }
                    .help("Re-run the install checks, e.g. after installing something yourself")
                Spacer()
            }
        }
        .padding()
    }
}

struct VoicesView: View {
    @ObservedObject var model: AppModel
    private let tiers = ["Default", "Kokoro", "Premium", "Enhanced", "Basic"]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Checked voices form the agent pool, best first. ▶ previews a voice.")
                    Text("Download or delete system voices (SIP-protected, ~5.8 GB) in Read & Speak → System Voice ⓘ → Manage Voices.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Manage System Voices…") {
                    NSWorkspace.shared.open(URL(
                        string: "x-apple.systempreferences:com.apple.Accessibility-Settings.extension?SpokenContent")!)
                }
            }
            List {
                ForEach(tiers, id: \.self) { tier in
                    let group = model.voices.filter { $0.tier == tier }
                    if !group.isEmpty {
                        Section(tier == "Default" ? "System default" : tier) {
                            ForEach(group) { voice in
                                HStack {
                                    Toggle(isOn: Binding(
                                        get: { model.enabled.contains(voice.id) },
                                        set: { on in
                                            if on { model.enabled.insert(voice.id) }
                                            else { model.enabled.remove(voice.id) }
                                        })) { Text(voice.label) }
                                    Spacer()
                                    Button { model.preview(voice.id) } label: {
                                        Image(systemName: "play.circle")
                                    }
                                    .buttonStyle(.borderless)
                                    .help("Preview this voice")
                                }
                            }
                        }
                    }
                }
                Section("Agent assignments (voices.json)") {
                    ForEach(model.agents.keys.sorted(), id: \.self) { agent in
                        HStack {
                            Text(agent)
                            Spacer()
                            Picker("", selection: Binding(
                                get: { model.agents[agent] ?? "default" },
                                set: { model.agents[agent] = $0 })) {
                                ForEach(model.orderedPool, id: \.self) { v in
                                    Text(v).tag(v)
                                }
                            }
                            .frame(width: 220)
                        }
                    }
                }
            }
            HStack {
                Button("Save") { model.save() }.keyboardShortcut("s")
                if model.savedFlash { Text("Saved ✓").foregroundStyle(.green) }
                Spacer()
                Button("Reload") { model.reload() }
            }
        }
        .padding()
    }
}

struct LexiconView: View {
    @ObservedObject var model: AppModel
    @State private var newWord = ""
    @State private var newPhonetic = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Pronunciations every agent learns, applied to all voices (lexicon.json).")
                .font(.caption).foregroundStyle(.secondary)
            List {
                ForEach(model.lexicon.keys.sorted(), id: \.self) { word in
                    HStack {
                        Text(word).bold().frame(width: 140, alignment: .leading)
                        Text("→ \(model.lexicon[word] ?? "")")
                        Spacer()
                        Button { model.lexicon.removeValue(forKey: word) } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.borderless)
                    }
                }
            }
            HStack {
                TextField("word (e.g. cmux)", text: $newWord).frame(width: 160)
                TextField("phonetic (e.g. sea mux)", text: $newPhonetic)
                Button("Teach") {
                    let w = newWord.trimmingCharacters(in: .whitespaces).lowercased()
                    let p = newPhonetic.trimmingCharacters(in: .whitespaces)
                    guard !w.isEmpty, !p.isEmpty else { return }
                    model.lexicon[w] = p
                    newWord = ""; newPhonetic = ""
                }
            }
            HStack {
                Button("Save") { model.save() }
                if model.savedFlash { Text("Saved ✓").foregroundStyle(.green) }
            }
        }
        .padding()
    }
}

@main
struct SquawkApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Squawk") {
            if model.repo != nil {
                TabView {
                    ChannelView(model: model).tabItem { Label("Channel", systemImage: "dot.radiowaves.left.and.right") }
                    InstallView(model: model).tabItem { Label("Install", systemImage: "wrench.and.screwdriver") }
                    VoicesView(model: model).tabItem { Label("Voices", systemImage: "waveform") }
                    LexiconView(model: model).tabItem { Label("Lexicon", systemImage: "character.book.closed") }
                }
                .frame(minWidth: 620, minHeight: 520)
            } else {
                VStack(spacing: 8) {
                    Text("Can't find the squawk repo").font(.title2)
                    Text("Keep Squawk.app inside the repo's app/ folder, or set SQUAWK_REPO.")
                        .foregroundStyle(.secondary)
                }
                .frame(minWidth: 620, minHeight: 520)
            }
        }
    }
}
