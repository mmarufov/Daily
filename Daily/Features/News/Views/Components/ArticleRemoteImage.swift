import SwiftUI

/// A lazy card owns this request; disappearance cancels its pipeline subscription.
/// Dimensions are device pixels, not points. The service caps them at 2048.
struct ArticleRemoteImage: View {
    let url: URL
    let pixelSize: Int
    var loader: ImageCacheService = .shared
    @State private var loaded: UIImage?

    private var requestID: String { "\(url.absoluteString)|\(pixelSize)" }

    var body: some View {
        Group {
            if let loaded {
                Image(uiImage: loaded).resizable().aspectRatio(contentMode: .fill)
            } else {
                EditionPalette.paperSecondary
            }
        }
        .accessibilityHidden(true)
        .task(id: requestID) {
            loaded = nil
            do {
                let result = try await loader.image(url: url, pixelSize: pixelSize)
                try Task.checkCancellation()
                loaded = result
            } catch { /* Decorative images never block reading or trigger retries. */ }
        }
    }
}

/// The clock is monotonic. Visibility interruptions reset the continuous dwell.
struct ImpressionDwell {
    private(set) var beganAt: Duration?
    private(set) var emitted = false

    mutating func update(visible: Bool, eligible: Bool, at time: Duration) {
        guard visible && eligible else { beganAt = nil; return }
        if beganAt == nil { beganAt = time }
    }

    mutating func consume(at time: Duration) -> Bool {
        guard !emitted, let beganAt, time - beganAt >= .seconds(1) else { return false }
        emitted = true
        return true
    }
}

private struct VisibleImpressionModifier: ViewModifier {
    let identity: String
    let enabled: Bool
    let action: () -> Void
    @Environment(\.scenePhase) private var scenePhase
    @State private var visible = false
    @State private var emittedIdentity: String?

    private var eligible: Bool { visible && enabled && scenePhase == .active }
    private var taskID: String { "\(identity)|\(eligible)" }

    func body(content: Content) -> some View {
        content
            .onScrollVisibilityChange(threshold: 0.5) { visible = $0 }
            .task(id: taskID) {
                guard eligible, emittedIdentity != identity else { return }
                let clock = ContinuousClock()
                let start = clock.now
                var dwell = ImpressionDwell()
                dwell.update(visible: true, eligible: true, at: .zero)
                do { try await clock.sleep(for: .seconds(1)) } catch { return }
                guard !Task.isCancelled, eligible,
                      dwell.consume(at: start.duration(to: clock.now)) else { return }
                emittedIdentity = identity
                action()
            }
    }
}

extension View {
    func deliveryImpression(identity: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        modifier(VisibleImpressionModifier(identity: identity, enabled: enabled, action: action))
    }
}
