import AppKit
import Foundation

let mockupRequested = CommandLine.arguments.contains("--mockup") || CommandLine.arguments.contains("--self-test-mockup")

enum ContentKind: String { case idle, music, ad, unknown }
enum SpotifyMode: String, CaseIterable {
    case hide, stay, lyrics
    var title: String {
        switch self { case .stay: return "Open + Stay"; case .hide: return "Open + Hide (default)"; case .lyrics: return "Open + Stay + Lyrics" }
    }
    var summary: String {
        switch self {
        case .stay: return "Open + Stay"
        case .hide: return "Open + Hide"
        case .lyrics: return "Open + Stay + Lyrics (when available)"
        }
    }
    var launchArguments: [String] { self == .hide ? ["-jg", "-b", "com.spotify.client"] : ["-b", "com.spotify.client"] }
    static func saved(_ raw: String?) -> SpotifyMode { raw.flatMap(SpotifyMode.init(rawValue:)) ?? .hide }
}
struct Playback {
    let state: String
    let uri: String
    let title: String
    var kind: ContentKind {
        guard state == "playing" else { return .idle }
        if ["spotify:track:", "spotify:episode:", "spotify:local:", "spotify:audiobook:"].contains(where: uri.hasPrefix) { return .music }
        if uri.hasPrefix("spotify:ad:") || uri.hasPrefix("spotify:advertisement:") { return .ad }
        // Only an explicit ad title is evidence; missing/unknown metadata is not.
        if uri.isEmpty && title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "advertisement" { return .ad }
        return .unknown
    }
    var adKey: String { uri.isEmpty ? "advertisement" : uri }
}

struct RecoveryGate {
    var candidate = ""
    var consecutive = 0
    var attempts: [String: Int] = [:]
    var lastAttempt = Date.distantPast
    mutating func observe(_ playback: Playback, now: Date = Date()) -> Bool {
        if playback.kind == .music { candidate = ""; consecutive = 0; attempts = [:]; return false }
        guard playback.kind == .ad else { candidate = ""; consecutive = 0; return false }
        if candidate == playback.adKey { consecutive += 1 } else { candidate = playback.adKey; consecutive = 1 }
        guard consecutive >= 2, now.timeIntervalSince(lastAttempt) >= 60, attempts[candidate, default: 0] < 2 else { return false }
        attempts[candidate, default: 0] += 1
        lastAttempt = now
        consecutive = 0
        return true
    }
}

struct CommandResult { let status: Int32; let output: String; let error: String }
func run(_ executable: String, _ arguments: [String], timeout: TimeInterval = 8) -> CommandResult {
    // Keep the preview unable to reach any shell or Spotify command.
    if mockupRequested { return CommandResult(status: -3, output: "", error: "Commands are disabled in the UI mockup") }
    let process = Process()
    let out = Pipe(), err = Pipe()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    process.standardOutput = out; process.standardError = err
    do { try process.run() } catch { return CommandResult(status: -1, output: "", error: error.localizedDescription) }
    let ended = DispatchSemaphore(value: 0)
    process.terminationHandler = { _ in ended.signal() }
    // Setting a handler after a very fast exit is not sufficient on all Foundation versions.
    if process.isRunning && ended.wait(timeout: .now() + timeout) == .timedOut {
        process.terminate()
        if ended.wait(timeout: .now() + 1) == .timedOut { Darwin.kill(process.processIdentifier, SIGKILL); process.waitUntilExit() }
        return CommandResult(status: -2, output: "", error: "Command timed out after \(Int(timeout)) seconds")
    }
    process.waitUntilExit()
    return CommandResult(status: process.terminationStatus,
        output: String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?.trimmingCharacters(in: .newlines) ?? "",
        error: String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?.trimmingCharacters(in: .newlines) ?? "")
}

let queryScript = """
with timeout of 4 seconds
  if application id "com.spotify.client" is not running then return "absent"
  tell application id "com.spotify.client"
    set s to player state as text
    if s is not "playing" then return s & linefeed & linefeed
    set u to ""
    set n to ""
    try
      set u to spotify url of current track
    end try
    try
      set n to name of current track
    end try
    if u is missing value then set u to ""
    if n is missing value then set n to ""
    return s & linefeed & u & linefeed & n
  end tell
end timeout
"""

func parsePlayback(_ result: CommandResult) -> Playback? {
    guard result.status == 0, !result.output.isEmpty, result.output != "absent" else { return nil }
    let fields = result.output.components(separatedBy: "\n")
    guard ["playing", "paused", "stopped"].contains(fields[0]) else { return nil }
    return Playback(state: fields[0], uri: fields.count > 1 ? fields[1] : "", title: fields.count > 2 ? fields.dropFirst(2).joined(separator: "\n") : "")
}

final class ActivityLog {
    let directory: URL
    let file: URL
    var lines: [String] = []
    let formatter = DateFormatter()
    let readLegacyLog: Bool
    init(directory: URL, readLegacyLog: Bool = true) {
        self.readLegacyLog = readLegacyLog
        self.directory = directory; file = directory.appendingPathComponent("activity.log")
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        reload()
    }
    func reload() {
        let current = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
        let previous = (try? String(contentsOf: directory.appendingPathComponent("activity.previous.log"), encoding: .utf8)) ?? ""
        lines = (previous + current).components(separatedBy: "\n").filter { !$0.isEmpty }.suffix(250).map { $0 }
        if lines.isEmpty && readLegacyLog {
            let old = (try? String(contentsOfFile: NSHomeDirectory() + "/spotify-ad-mute.log", encoding: .utf8)) ?? ""
            lines = old.components(separatedBy: "\n").filter { !$0.isEmpty }.suffix(30).map { "[previous helper] " + $0 }
        }
    }
    func add(_ level: String, _ message: String) {
        let clean = message.replacingOccurrences(of: "\n", with: " ")
        let line = "\(formatter.string(from: Date()))  \(level)  \(clean)"
        do {
            let attributes = try? FileManager.default.attributesOfItem(atPath: file.path)
            if (attributes?[.size] as? NSNumber)?.intValue ?? 0 > 512_000 {
                let previous = directory.appendingPathComponent("activity.previous.log")
                if FileManager.default.fileExists(atPath: previous.path) { try FileManager.default.removeItem(at: previous) }
                try FileManager.default.moveItem(at: file, to: previous)
            }
            if !FileManager.default.fileExists(atPath: file.path) { FileManager.default.createFile(atPath: file.path, contents: nil) }
            let handle = try FileHandle(forWritingTo: file)
            try handle.seekToEnd(); try handle.write(contentsOf: Data((line + "\n").utf8)); try handle.close()
        } catch { lines.append("Log write failed: \(error.localizedDescription)") }
        lines.append(line)
        if lines.count > 250 { lines.removeFirst(lines.count - 250) }
    }
}

final class SpotifyControl: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var instructionsWindow: NSWindow?
    var statusItem: NSStatusItem!
    let status = NSTextField(labelWithString: "Waiting for Spotify")
    let detail = NSTextField(labelWithString: "Open Spotify to start this session.")
    let refreshed = NSTextField(labelWithString: "")
    let activity = NSTextView()
    var toggle: NSButton!
    var playButton: NSButton!
    var intervalPicker: NSPopUpButton!
    var dailyToggle: NSButton!
    var modePicker: NSPopUpButton!
    let modeDescription = NSTextField(labelWithString: "")
    var timer: Timer?
    var daily: Timer?
    var epoch = UUID()
    var session = false
    var recovering = false
    var querying = false
    var gate = RecoveryGate()
    var lastMessage = ""
    var lastRefresh = Date.distantPast
    var lastKind: ContentKind?
    let queue = DispatchQueue(label: "SpotifyControl.commands")
    let log: ActivityLog
    let mockup: Bool
    var mockupEnabled = true
    var mockupInterval = 2.0
    var mockupDaily = true
    var mockupMode = SpotifyMode.hide
    var mockupPlaying = true
    var enabled: Bool {
        get { mockup ? mockupEnabled : UserDefaults.standard.object(forKey: "helperEnabled") as? Bool ?? true }
        set { if mockup { mockupEnabled = newValue } else { UserDefaults.standard.set(newValue, forKey: "helperEnabled") } }
    }
    var checkInterval: Double {
        if mockup { return mockupInterval }
        let value = UserDefaults.standard.double(forKey: "checkInterval")
        return [1.0, 2.0, 5.0, 10.0].contains(value) ? value : 2
    }
    var dailyEnabled: Bool { mockup ? mockupDaily : UserDefaults.standard.object(forKey: "dailyRefresh") as? Bool ?? true }
    var mode: SpotifyMode { mockup ? mockupMode : SpotifyMode.saved(UserDefaults.standard.string(forKey: "spotifyMode")) }
    init(directory: URL, mockup: Bool = false) {
        self.mockup = mockup
        log = ActivityLog(directory: directory, readLegacyLog: !mockup)
        super.init()
    }
    var spotify: NSRunningApplication? {
        guard !mockup else { return nil }
        return NSWorkspace.shared.runningApplications.first { $0.bundleIdentifier == "com.spotify.client" && !$0.isTerminated }
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(mockup ? .regular : .accessory)
        makeWindow()
        _ = prepareInstructionsFile()
        if mockup {
            event("MOCKUP", "Sample dashboard opened. Spotify is not connected.")
            showDashboard()
            return
        }
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "♫"
        let menu = NSMenu()
        let show = NSMenuItem(title: "Spotify Control Dashboard", action: #selector(showDashboard), keyEquivalent: "")
        show.target = self; menu.addItem(show)
        menu.addItem(NSMenuItem.separator())
        let info = NSMenuItem(title: "Starts when you open Spotify", action: nil, keyEquivalent: "")
        menu.addItem(info); statusItem.menu = menu
        let center = NSWorkspace.shared.notificationCenter
        center.addObserver(self, selector: #selector(appLaunched(_:)), name: NSWorkspace.didLaunchApplicationNotification, object: nil)
        center.addObserver(self, selector: #selector(appTerminated(_:)), name: NSWorkspace.didTerminateApplicationNotification, object: nil)
        if spotify != nil { startSession() }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { showDashboard(); return true }
    func windowWillClose(_ notification: Notification) {
        if mockup, let closed = notification.object as? NSWindow, closed === window { NSApp.terminate(nil) }
    }
    func applicationWillTerminate(_ notification: Notification) {
        if mockup { try? FileManager.default.removeItem(at: log.directory) }
    }
    func label(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular) -> NSTextField {
        let field = NSTextField(labelWithString: text)
        field.font = .systemFont(ofSize: size, weight: weight)
        field.textColor = .labelColor
        return field
    }
    func makeWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 790, height: 700), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = mockup ? "Spotify Control — UI Mockup" : "Spotify Control Dashboard"
        window.appearance = NSAppearance(named: .darkAqua)
        window.minSize = NSSize(width: 700, height: 650)
        window.isReleasedWhenClosed = false; window.delegate = self
        window.center()
        let root = NSStackView(); root.orientation = .vertical; root.alignment = .leading; root.spacing = 12
        root.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(root)
        NSLayoutConstraint.activate([root.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 26), root.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -26), root.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 24), root.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -24)])
        root.addArrangedSubview(label("Spotify Control", size: 29, weight: .bold))
        let intro = label(mockup ? "UI mockup · Sample playback only · Spotify is not connected" : "Your playback helper, controls, and activity in one place.", size: 13)
        intro.textColor = .secondaryLabelColor; root.addArrangedSubview(intro)
        status.font = .systemFont(ofSize: 18, weight: .semibold); status.textColor = NSColor.systemGreen
        root.addArrangedSubview(status)
        detail.font = .systemFont(ofSize: 13); detail.maximumNumberOfLines = 2; detail.lineBreakMode = .byTruncatingTail
        root.addArrangedSubview(detail)
        detail.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        let controls = NSStackView(); controls.orientation = .horizontal; controls.spacing = 12
        toggle = NSButton(checkboxWithTitle: "Ad helper enabled", target: self, action: #selector(toggleHelper))
        toggle.state = enabled ? .on : .off
        let refresh = NSButton(title: "Refresh", target: self, action: #selector(refreshClicked)); refresh.bezelStyle = .rounded
        playButton = NSButton(title: "Play / Pause", target: self, action: #selector(playPause)); playButton.bezelStyle = .rounded
        let instructions = NSButton(title: "Instructions", target: self, action: #selector(showInstructions)); instructions.bezelStyle = .rounded
        for button in [toggle!, refresh, playButton!, instructions] { controls.addArrangedSubview(button) }
        root.addArrangedSubview(controls)
        let settings = NSStackView(); settings.orientation = .horizontal; settings.spacing = 12
        settings.addArrangedSubview(label("Check every", size: 11))
        intervalPicker = NSPopUpButton(frame: .zero, pullsDown: false)
        intervalPicker.addItems(withTitles: ["1 second", "2 seconds", "5 seconds", "10 seconds"])
        intervalPicker.selectItem(at: [1.0, 2.0, 5.0, 10.0].firstIndex(of: checkInterval) ?? 1)
        intervalPicker.target = self; intervalPicker.action = #selector(settingsChanged)
        settings.addArrangedSubview(intervalPicker)
        dailyToggle = NSButton(checkboxWithTitle: "Refresh daily", target: self, action: #selector(settingsChanged))
        dailyToggle.state = dailyEnabled ? .on : .off; settings.addArrangedSubview(dailyToggle)
        root.addArrangedSubview(settings)
        let modes = NSStackView(); modes.orientation = .horizontal; modes.spacing = 16
        modes.addArrangedSubview(label("Modes", size: 15, weight: .semibold))
        modePicker = NSPopUpButton(frame: .zero, pullsDown: false)
        modePicker.addItems(withTitles: SpotifyMode.allCases.map { $0.title })
        modePicker.selectItem(at: SpotifyMode.allCases.firstIndex(of: mode) ?? 0)
        modePicker.target = self; modePicker.action = #selector(modeChanged)
        modes.addArrangedSubview(modePicker); root.addArrangedSubview(modes)
        modeDescription.font = .systemFont(ofSize: 11); modeDescription.textColor = .secondaryLabelColor
        modeDescription.stringValue = mode.summary + (mockup ? "  ·  Preview only" : "  ·  Applies after an ad recovery")
        root.addArrangedSubview(modeDescription)
        refreshed.font = .systemFont(ofSize: 11); refreshed.textColor = .secondaryLabelColor
        root.addArrangedSubview(refreshed)
        root.addArrangedSubview(label("Activity log", size: 15, weight: .semibold))
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder
        activity.isEditable = false; activity.isSelectable = true; activity.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        activity.backgroundColor = NSColor(calibratedWhite: 0.09, alpha: 1); activity.textColor = NSColor(calibratedWhite: 0.82, alpha: 1)
        activity.textContainerInset = NSSize(width: 12, height: 12)
        activity.isVerticallyResizable = true; activity.isHorizontallyResizable = false
        activity.minSize = NSSize(width: 0, height: 0); activity.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        activity.autoresizingMask = [.width]; activity.textContainer?.widthTracksTextView = true
        scroll.documentView = activity; root.addArrangedSubview(scroll)
        scroll.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 150).isActive = true
        let footer = label(mockup ? "All controls are simulated. Changes last until this window closes. Your installed helper is separate." : "Checks run only while Spotify is open. Your selected mode controls reopening. Unknown metadata is left alone.", size: 11)
        footer.textColor = .secondaryLabelColor; footer.maximumNumberOfLines = 2; root.addArrangedSubview(footer)
        footer.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        drawLog(); updateRefreshLabel()
    }
    @objc func showDashboard() { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); refreshSnapshot(logEvent: false) }
    var instructionsFile: URL { log.directory.appendingPathComponent("Spotify Control Instructions.md") }
    func prepareInstructionsFile() -> Bool {
        do {
            if !FileManager.default.fileExists(atPath: instructionsFile.path) {
                guard let resource = Bundle.main.url(forResource: "Spotify Control Instructions", withExtension: "md") else {
                    event("ERROR", "The bundled instructions file is missing."); return false
                }
                try FileManager.default.copyItem(at: resource, to: instructionsFile)
            }
            return true
        } catch { event("ERROR", "Unable to create instructions file: " + error.localizedDescription); return false }
    }
    @objc func showInstructions() {
        guard prepareInstructionsFile() else { return }
        do {
            let text = try String(contentsOf: instructionsFile, encoding: .utf8)
            if instructionsWindow == nil {
                let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 780, height: 640), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
                panel.title = "Spotify Control Instructions"; panel.appearance = NSAppearance(named: .darkAqua)
                panel.isReleasedWhenClosed = false; panel.minSize = NSSize(width: 600, height: 400); panel.center()
                let root = NSStackView(); root.orientation = .vertical; root.alignment = .leading; root.spacing = 14
                root.translatesAutoresizingMaskIntoConstraints = false; panel.contentView!.addSubview(root)
                NSLayoutConstraint.activate([root.leadingAnchor.constraint(equalTo: panel.contentView!.leadingAnchor, constant: 22), root.trailingAnchor.constraint(equalTo: panel.contentView!.trailingAnchor, constant: -22), root.topAnchor.constraint(equalTo: panel.contentView!.topAnchor, constant: 20), root.bottomAnchor.constraint(equalTo: panel.contentView!.bottomAnchor, constant: -20)])
                root.addArrangedSubview(label("Instructions", size: 22, weight: .semibold))
                let buttons = NSStackView(); buttons.spacing = 12
                let fileButton = NSButton(title: "Open file", target: self, action: #selector(openInstructionsFile)); fileButton.bezelStyle = .rounded
                buttons.addArrangedSubview(fileButton); root.addArrangedSubview(buttons)
                let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder
                let reader = NSTextView(); reader.identifier = NSUserInterfaceItemIdentifier("instructionsReader")
                reader.isEditable = false; reader.isSelectable = true; reader.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
                reader.textContainerInset = NSSize(width: 16, height: 16); reader.isVerticallyResizable = true
                reader.isHorizontallyResizable = false; reader.autoresizingMask = [.width]; reader.textContainer?.widthTracksTextView = true
                reader.minSize = .zero; reader.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
                scroll.documentView = reader; root.addArrangedSubview(scroll)
                scroll.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true; scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 200).isActive = true
                instructionsWindow = panel
            }
            let root = instructionsWindow!.contentView!.subviews.compactMap { $0 as? NSStackView }.first!
            let reader = root.arrangedSubviews.compactMap { $0 as? NSScrollView }.first!.documentView as! NSTextView
            reader.string = text; reader.scrollRangeToVisible(NSRange(location: 0, length: 0))
            instructionsWindow!.makeKeyAndOrderFront(nil)
        } catch { event("ERROR", "Unable to read instructions: " + error.localizedDescription) }
    }
    @objc func openInstructionsFile() {
        if mockup { event("MOCKUP", "Open file selected; no external app opened."); return }
        if prepareInstructionsFile() { if !NSWorkspace.shared.open(instructionsFile) { event("ERROR", "No application could open the instructions file.") } }
    }
    @objc func appLaunched(_ note: Notification) {
        guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, app.bundleIdentifier == "com.spotify.client" else { return }
        if recovering { return }
        startSession()
    }
    @objc func appTerminated(_ note: Notification) {
        guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, app.bundleIdentifier == "com.spotify.client" else { return }
        if !recovering { stopSession() }
    }
    func startSession() {
        guard !mockup else { return }
        guard !session else { return }
        session = true; epoch = UUID(); gate = RecoveryGate(); lastKind = nil; lastMessage = ""
        event("INFO", "Spotify opened. Playback monitoring started.")
        window.orderFront(nil) // Show dashboard without taking focus away from Spotify.
        if window.isVisible { event("INFO", "Spotify Control Dashboard opened.") }
        startTimers(); refreshSnapshot(logEvent: false)
    }
    func startTimers() {
        guard !mockup else { return }
        timer?.invalidate(); daily?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: checkInterval, repeats: true) { [weak self] _ in self?.tick() }
        if dailyEnabled { daily = Timer.scheduledTimer(withTimeInterval: 86400, repeats: true) { [weak self] _ in self?.refreshSnapshot(logEvent: true) } } else { daily = nil }
    }
    func stopSession() {
        guard session else { return }
        session = false; epoch = UUID(); recovering = false; querying = false
        timer?.invalidate(); daily?.invalidate(); timer = nil; daily = nil
        event("INFO", "Spotify closed. Playback monitoring stopped.")
        status.stringValue = "Waiting for Spotify"; detail.stringValue = "Open Spotify to start this session."
        playButton.isEnabled = false
        window.orderOut(nil)
    }
    func event(_ level: String, _ text: String) { log.add(level, text); drawLog() }
    func drawLog() { activity.string = log.lines.joined(separator: "\n"); activity.scrollToEndOfDocument(nil) }
    func updateRefreshLabel() {
        let stamp = lastRefresh == .distantPast ? "Not refreshed yet" : "Last refresh: " + log.formatter.string(from: lastRefresh)
        refreshed.stringValue = stamp + (dailyEnabled ? "  ·  Daily refresh while Spotify is open" : "  ·  Manual refresh")
    }
    @objc func settingsChanged() {
        let interval = [1.0, 2.0, 5.0, 10.0][intervalPicker.indexOfSelectedItem]
        if mockup {
            mockupInterval = interval
            mockupDaily = dailyToggle.state == .on
        } else {
            UserDefaults.standard.set(interval, forKey: "checkInterval")
            UserDefaults.standard.set(dailyToggle.state == .on, forKey: "dailyRefresh")
        }
        if session { startTimers() }
        updateRefreshLabel(); event(mockup ? "MOCKUP" : "INFO", "\(mockup ? "Sample settings changed" : "Settings saved"). Check interval: \(Int(checkInterval))s. Daily refresh: \(dailyEnabled ? "on" : "off").")
    }
    @objc func modeChanged() {
        let chosen = SpotifyMode.allCases[modePicker.indexOfSelectedItem]
        if mockup { mockupMode = chosen } else { UserDefaults.standard.set(chosen.rawValue, forKey: "spotifyMode") }
        modeDescription.stringValue = chosen.summary + (mockup ? "  ·  Preview only" : "  ·  Applies after an ad recovery")
        event(mockup ? "MOCKUP" : "INFO", mockup ? "Sample mode changed: \(chosen.title)." : "Mode saved: \(chosen.title). Applies to the next ad recovery.")
    }
    @objc func refreshClicked() { refreshSnapshot(logEvent: true) }
    func refreshSnapshot(logEvent: Bool) {
        log.reload(); lastRefresh = Date(); updateRefreshLabel()
        if logEvent { event("INFO", "Dashboard refreshed.") } else { drawLog() }
        if mockup { renderMockup(); return }
        if spotify != nil { tick() } else { status.stringValue = "Waiting for Spotify"; detail.stringValue = "Open Spotify to start this session."; playButton.isEnabled = false }
    }
    @objc func toggleHelper() {
        enabled = toggle.state == .on; gate = RecoveryGate()
        if !enabled && recovering { epoch = UUID(); recovering = false; if session { startTimers() } }
        event("INFO", enabled ? "Ad helper enabled." : "Ad helper disabled.")
        tick()
    }
    @objc func playPause() {
        if mockup {
            mockupPlaying.toggle()
            event("MOCKUP", mockupPlaying ? "Sample playback resumed." : "Sample playback paused.")
            renderMockup()
            return
        }
        guard spotify != nil, !recovering else { return }
        let token = epoch
        queue.async {
            guard DispatchQueue.main.sync(execute: { token == self.epoch && self.session && self.spotify != nil && !self.recovering }) else { return }
            let result = run("/usr/bin/osascript", ["-e", "if application id \"com.spotify.client\" is running then tell application id \"com.spotify.client\" to playpause"])
            DispatchQueue.main.async {
                guard token == self.epoch else { return }
                self.event(result.status == 0 ? "INFO" : "ERROR", result.status == 0 ? "Play / Pause requested." : "Play / Pause failed: " + result.error)
                self.tick()
            }
        }
    }
    func tick() {
        if mockup { renderMockup(); return }
        guard session, spotify != nil else { if session && !recovering { stopSession() }; return }
        guard !querying, !recovering else { return }
        playButton.isEnabled = true
        if dailyEnabled && Date().timeIntervalSince(lastRefresh) >= 86400 { refreshSnapshot(logEvent: true); return }
        guard enabled else { status.stringValue = "Helper disabled"; detail.stringValue = "Spotify stays under your control."; return }
        querying = true
        let token = epoch
        queue.async {
            let result = run("/usr/bin/osascript", ["-e", queryScript])
            DispatchQueue.main.async {
                guard token == self.epoch else { return }
                self.querying = false
                guard self.spotify != nil else { self.stopSession(); return }
                guard let playback = parsePlayback(result) else {
                    _ = self.gate.observe(Playback(state: "playing", uri: "", title: ""))
                    let message = result.error.isEmpty ? "Playback metadata unavailable; Spotify left alone." : "Metadata query failed: " + result.error
                    if message != self.lastMessage { self.event("ERROR", message); self.lastMessage = message }
                    self.status.stringValue = "Waiting for playback details"
                    self.detail.stringValue = result.error.contains("1743") ? "Allow Spotify Control to control Spotify in System Settings → Privacy & Security → Automation." : "Spotify will be left alone until a reliable result is available."
                    return
                }
                self.lastMessage = ""
                if self.lastKind != playback.kind {
                    self.event("INFO", "Playback state: \(playback.kind.rawValue)." + (playback.kind == .unknown ? " No action taken." : ""))
                    self.lastKind = playback.kind
                }
                self.status.stringValue = playback.kind == .ad ? "Ad detected — confirming" : playback.kind == .unknown ? "Unrecognized playback — left alone" : playback.state == "playing" ? "Spotify is playing" : "Spotify is " + playback.state
                self.detail.stringValue = playback.title.isEmpty ? "Helper active only for this Spotify session." : playback.title
                if self.gate.observe(playback) { self.recover(token: token) }
            }
        }
    }
    func valid(_ token: UUID) -> Bool { DispatchQueue.main.sync { token == self.epoch && self.enabled && self.session } }
    func isSpotifyRunning() -> Bool { DispatchQueue.main.sync { self.spotify != nil } }
    func recover(token: UUID) {
        guard !mockup else { return }
        let recoveryMode = mode
        recovering = true; playButton.isEnabled = false
        status.stringValue = "Restarting Spotify"
        event("INFO", "Confirmed ad twice. Requesting normal quit. Mode: \(recoveryMode.summary).")
        queue.async {
            var error: String?
            if !self.valid(token) || !self.isSpotifyRunning() { error = "Session ended before recovery." }
            if error == nil {
                let quit = run("/usr/bin/osascript", ["-e", "with timeout of 4 seconds\nif application id \"com.spotify.client\" is running then tell application id \"com.spotify.client\" to quit\nend timeout"])
                if quit.status != 0 { error = "Quit failed: " + quit.error }
            }
            if error == nil {
                let deadline = Date().addingTimeInterval(8)
                while self.isSpotifyRunning() && Date() < deadline && self.valid(token) { Thread.sleep(forTimeInterval: 0.1) }
                if !self.valid(token) { error = "Recovery canceled." }
                else if self.isSpotifyRunning() { error = "Spotify did not quit in time. No force-quit performed." }
            }
            if error == nil && self.valid(token) {
                let opened = run("/usr/bin/open", recoveryMode.launchArguments)
                if opened.status != 0 { error = "Reopen failed: " + opened.error }
            }
            if error == nil {
                let deadline = Date().addingTimeInterval(15)
                var ready = false
                while Date() < deadline && self.valid(token) {
                    if self.isSpotifyRunning() {
                        let probe = run("/usr/bin/osascript", ["-e", "with timeout of 2 seconds\nif application id \"com.spotify.client\" is not running then return \"absent\"\ntell application id \"com.spotify.client\" to return player state as text\nend timeout"], timeout: 3)
                        if probe.status == 0 && ["playing", "paused", "stopped"].contains(probe.output) { ready = true; break }
                    }
                    Thread.sleep(forTimeInterval: 0.25)
                }
                if !self.valid(token) { error = "Recovery canceled." }
                else if !ready { error = "Spotify did not become ready in time; no playback command sent." }
                else if !self.isSpotifyRunning() { error = "Spotify was closed; playback was not resumed." }
                else {
                    let played = run("/usr/bin/osascript", ["-e", "with timeout of 4 seconds\nif application id \"com.spotify.client\" is running then\ntell application id \"com.spotify.client\" to play\nelse\nerror \"Spotify closed\"\nend if\nend timeout"])
                    if played.status != 0 { error = "Resume failed: " + played.error }
                    else {
                        let confirmationDeadline = Date().addingTimeInterval(6)
                        var playing = false
                        while Date() < confirmationDeadline && self.valid(token) && self.isSpotifyRunning() {
                            let check = run("/usr/bin/osascript", ["-e", queryScript], timeout: 5)
                            if parsePlayback(check)?.kind == .music { playing = true; break }
                            Thread.sleep(forTimeInterval: 0.25)
                        }
                        if !playing { error = "Playback was requested but could not be confirmed. No additional play command sent." }
                    }
                }
            }
            if error == nil && self.valid(token) && self.isSpotifyRunning() {
                if recoveryMode == .hide {
                    DispatchQueue.main.sync {
                        guard token == self.epoch, let app = self.spotify else { return }
                        if app.isHidden || app.hide() { self.event("INFO", "Spotify hidden after recovery.") }
                        else { self.event("WARNING", "Spotify reopened, but hiding was not accepted.") }
                    }
                } else if recoveryMode == .lyrics {
                    let lyrics = run("/usr/bin/open", ["-b", "com.spotify.client", "spotify:app:lyrics"])
                    let message = lyrics.status == 0 ? "Spotify Lyrics: lyrics view requested. Availability depends on the current song and Spotify version; the view is not visually verified." : "Spotify Lyrics: unable to request lyrics: " + lyrics.error
                    DispatchQueue.main.async { if token == self.epoch { self.event(lyrics.status == 0 ? "INFO" : "WARNING", message) } }
                }
            }
            let failure = error
            DispatchQueue.main.async {
                guard token == self.epoch else { return }
                self.recovering = false
                self.event(failure == nil ? "INFO" : "ERROR", failure ?? "Spotify recovered; playback confirmed. Mode: \(recoveryMode.title).")
                if self.spotify == nil { self.stopSession() } else { self.tick() }
            }
        }
    }
    func renderMockup() {
        status.stringValue = !enabled ? "UI mockup · Helper disabled" : mockupPlaying ? "UI mockup · Playing" : "UI mockup · Paused"
        detail.stringValue = "Sample Artist — Sample Song"
        playButton.isEnabled = true
        updateRefreshLabel()
    }
}

func selfTest() {
    func check(_ condition: @autoclosure () -> Bool, _ name: String) { if !condition() { fputs("FAIL: \(name)\n", stderr); exit(1) } }
    check(Playback(state: "playing", uri: "", title: "").kind == .unknown, "empty metadata is not an ad")
    check(SpotifyMode.saved(nil) == .hide, "Open + Hide is the default")
    check(SpotifyMode.saved("invalid") == .hide, "invalid mode falls back to hide")
    check(SpotifyMode.saved("stay") == .stay, "an explicitly saved visible mode is preserved")
    check(SpotifyMode.saved("hide").launchArguments.contains("-jg"), "hide mode opens hidden")
    check(!SpotifyMode.saved("lyrics").launchArguments.contains("-jg"), "lyrics mode stays visible")
    check(Bundle.main.url(forResource: "Spotify Control Instructions", withExtension: "md") != nil, "instructions file bundled in the app")
    check(Playback(state: "playing", uri: "https://unknown", title: "Spotify").kind == .unknown, "unknown URI is left alone")
    for uri in ["spotify:track:1", "spotify:episode:1", "spotify:local:artist:album:title:1", "spotify:audiobook:1"] {
        check(Playback(state: "playing", uri: uri, title: "Advertisement").kind == .music, "legitimate URI takes priority")
    }
    check(Playback(state: "paused", uri: "spotify:ad:1", title: "Advertisement").kind == .idle, "paused ad is left alone")
    check(parsePlayback(CommandResult(status: 1, output: "playing\nspotify:ad:1\nAdvertisement", error: "denied")) == nil, "failed query never triggers")
    check(parsePlayback(CommandResult(status: 0, output: "garbage", error: "")) == nil, "invalid response rejected")
    check(parsePlayback(CommandResult(status: 0, output: "absent", error: "")) == nil, "closed app does not trigger")
    check(parsePlayback(CommandResult(status: 0, output: "paused", error: ""))?.kind == .idle, "paused response accepted without track")
    check(parsePlayback(CommandResult(status: 0, output: "playing\nspotify:ad:1\nAdvertisement", error: ""))?.kind != .music, "a still-playing ad cannot confirm recovery")
    let ad = Playback(state: "playing", uri: "spotify:ad:1", title: "Advertisement")
    var gate = RecoveryGate(); let date = Date(timeIntervalSince1970: 100000)
    check(!gate.observe(ad, now: date), "first detection waits")
    check(gate.observe(ad, now: date.addingTimeInterval(2)), "second detection triggers")
    check(!gate.observe(ad, now: date.addingTimeInterval(4)), "restart cooldown")
    check(!gate.observe(ad, now: date.addingTimeInterval(6)), "persistent ad cooldown")
    check(gate.observe(ad, now: date.addingTimeInterval(63)), "bounded retry allowed")
    for i in 0..<10 { check(!gate.observe(ad, now: date.addingTimeInterval(150 + Double(i))), "at most two attempts per ad") }
    _ = gate.observe(Playback(state: "playing", uri: "spotify:track:1", title: "Music"), now: date.addingTimeInterval(200))
    check(!gate.observe(ad, now: date.addingTimeInterval(201)), "music resets confirmation")
    check(gate.observe(ad, now: date.addingTimeInterval(203)), "music resets attempt cap")
    let result = run("/bin/sleep", ["2"], timeout: 0.05)
    check(result.status == -2, "hung command terminated")
    let logDir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("spotify-control-test-" + UUID().uuidString)
    let activityLog = ActivityLog(directory: logDir)
    activityLog.add("ERROR", "Permission denied\nnext line")
    let reader = ActivityLog(directory: logDir)
    check(reader.lines.last?.contains("Permission denied next line") == true, "errors persist as a single log entry")
    try! Data(repeating: 65, count: 512_001).write(to: activityLog.file)
    activityLog.add("INFO", "rotated")
    check(FileManager.default.fileExists(atPath: logDir.appendingPathComponent("activity.previous.log").path), "large log rotated")
    check((try! String(contentsOf: activityLog.file)).contains("rotated"), "new log retains latest event")
    try! FileManager.default.removeItem(at: logDir)
    print("PASS: modes, bundled instructions, classification, malformed/error responses, confirmation, cooldown, retry limits, reset, command timeout, log persistence and rotation")
}

func mockupSelfTest() {
    func check(_ condition: @autoclosure () -> Bool, _ name: String) { if !condition() { fputs("FAIL: \(name)\n", stderr); exit(1) } }
    _ = NSApplication.shared
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("spotify-ui-test-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let settingsBefore = (UserDefaults.standard.persistentDomain(forName: "com.user.spotifycontrol") ?? [:]) as NSDictionary
    let control = SpotifyControl(directory: directory, mockup: true)
    control.makeWindow()
    control.renderMockup()
    check(control.log.lines.isEmpty, "mockup does not read the installed helper's logs")
    control.toggle.state = .off; control.toggleHelper()
    check(!control.enabled && control.status.stringValue.contains("disabled"), "mockup helper toggle updates the UI")
    control.intervalPicker.selectItem(at: 2); control.dailyToggle.state = .off; control.settingsChanged()
    control.modePicker.selectItem(at: SpotifyMode.allCases.firstIndex(of: .stay)!); control.modeChanged()
    check(control.checkInterval == 5 && !control.dailyEnabled && control.mode == .stay, "mockup settings stay in memory")
    control.playPause()
    check(!control.mockupPlaying, "mockup playback changes sample state only")
    control.refreshSnapshot(logEvent: true)
    control.startSession(); control.startTimers(); control.recover(token: UUID())
    check(control.spotify == nil && !control.session && control.timer == nil && control.daily == nil && !control.recovering, "mockup cannot monitor or recover Spotify")
    check(run("/bin/echo", ["must not run"]).status == -3, "shell commands are blocked in mockup mode")
    check(settingsBefore.isEqual(to: UserDefaults.standard.persistentDomain(forName: "com.user.spotifycontrol") ?? [:]), "installed helper settings are unchanged")
    print("PASS: mockup controls, temporary logs, isolated settings, no polling, no recovery and no shell commands")
}

if CommandLine.arguments.contains("--self-test-mockup") { mockupSelfTest(); exit(0) }
if CommandLine.arguments.contains("--self-test") { selfTest(); exit(0) }
let base = mockupRequested ? FileManager.default.temporaryDirectory.appendingPathComponent("spotify-ui-mockup-" + UUID().uuidString) : URL(fileURLWithPath: CommandLine.arguments.contains("--data-dir") ? CommandLine.arguments[CommandLine.arguments.firstIndex(of: "--data-dir")! + 1] : NSHomeDirectory() + "/Library/Application Support/Spotify Control")
try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
if !mockupRequested {
    let lockDescriptor = Darwin.open(base.appendingPathComponent("session.lock").path, O_CREAT | O_RDWR, 0o600)
    guard lockDescriptor >= 0, flock(lockDescriptor, LOCK_EX | LOCK_NB) == 0 else { exit(0) }
}
let app = NSApplication.shared
let delegate = SpotifyControl(directory: base, mockup: mockupRequested)
app.delegate = delegate
app.run()
