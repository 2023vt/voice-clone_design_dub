import SwiftUI
import VoiceStudioKit

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        @Bindable var model = model
        Page {
            if model.connection.client != nil {
                Card {
                    Text(model.t("mobile.settings.connection"))
                    if let host = model.connection.active { Text(model.t("mobile.connect.connected_to", ["host": host.label])) }
                    NavigationLink(model.t("mobile.connect.saved_hosts")) { ConnectView() }.disabled(model.busy || BackgroundUpload.shared.pending != nil)
                    Button(model.t("mobile.connect.disconnect"), role: .destructive) { Task { await model.perform(connectionChange: true) { model.pauseMonitor(); await BackgroundUpload.shared.cancel(); try await model.connection.disconnect(); model.profiles = []; model.history = []; model.dubHistory = []; model.inventory = nil } } }.disabled(model.busy)
                }
                Card {
                    Text(model.t("mobile.settings.appearance"))
                    ChoicePicker(label: model.t("mobile.settings.mode"), selection: Binding(get: { model.theme.mode.rawValue }, set: { model.theme.mode = ThemeMode(rawValue: $0) ?? .dark }), options: ThemeMode.allCases.map { SelectionOption(id: $0.rawValue, title: model.t("mobile.settings.mode_" + $0.rawValue)) })
                    palette(key: "mobile.settings.light_palette", selection: $model.theme.lightPalette)
                    palette(key: "mobile.settings.dark_palette", selection: $model.theme.darkPalette)
                    ForEach(Appearance.allCases, id: \.self) { appearance in
                        let preview = Theme(palette: appearance == .light ? model.theme.lightPalette : model.theme.darkPalette, appearance: appearance)
                        Label(model.t(appearance == .light ? "mobile.settings.light_palette" : "mobile.settings.dark_palette"), systemImage: "waveform").padding(Theme.compactInset)
                            .background(preview.color("messageAction"), in: RoundedRectangle(cornerRadius: VSTokens.radiusControl))
                            .foregroundStyle(preview.color("messageActionForeground"))
                    }
                }
                Card {
                    ChoicePicker(label: model.t("mobile.settings.language"), selection: $model.language, options:
                        [SelectionOption(id: "", title: model.t("mobile.ios.language_system"))] + L10n.languages.map { SelectionOption(id: $0, title: Locale(identifier: $0).localizedString(forIdentifier: $0) ?? $0) }).accessibilityIdentifier("settings.language")
                    Toggle(model.t("mobile.settings.notifications"), isOn: Binding(get: { model.notifications }, set: { value in Task { await model.enableNotifications(value) } })).frame(minHeight: 44)
                    Text(model.t("mobile.settings.notifications_help"))
                }
            }
            Card {
                Text(model.t("mobile.settings.privacy"))
                Text(model.t("mobile.settings.privacy_help"))
                Toggle(model.t("privacy.analytics_title"), isOn: $model.analytics).frame(minHeight: 44)
                Text(model.t("mobile.ios.privacy_local"))
            }
            Card {
                Text(model.t("mobile.settings.about"))
                Text(model.t("mobile.settings.version", ["version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? model.t("common.unknown")]))
                NavigationLink(model.t("mobile.settings.licenses")) { LicensesView() }
                if let host = model.connection.active {
                    Link(model.t("mobile.ios.model_licenses"), destination: host.url)
                    Text(model.t("mobile.ios.licenses_host"))
                }
            }
        }.navigationTitle(model.t("mobile.tabs.settings")).navigationBarTitleDisplayMode(.large)
    }
    private func palette(key: String, selection: Binding<String>) -> some View {
        ChoicePicker(label: model.t(key), selection: selection, options: VSTokens.palettes.map { SelectionOption(id: $0.id, title: Theme.paletteLabel($0, l10n: model.l10n)) })
    }
}
struct LicensesView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        Page {
            Text(model.t("mobile.ios.licenses_app"))
            Text(model.t("mobile.ios.licenses_inter"))
            if let url = Bundle.main.url(forResource: "OFL", withExtension: "txt"), let text = try? String(contentsOf: url, encoding: .utf8) { Text(text).textSelection(.enabled) }
            if let url = Bundle.main.url(forResource: "AGPL-3.0", withExtension: "txt"), let text = try? String(contentsOf: url, encoding: .utf8) { Text(text).textSelection(.enabled) }
        }.navigationTitle(model.t("mobile.settings.licenses"))
    }
}
