import SwiftUI

struct ArticleReaderButton<Label: View>: View {
    let article: NewsArticle
    let position: Int?
    @Binding var destination: ArticleReaderDestination?
    private let label: () -> Label

    init(
        article: NewsArticle,
        position: Int? = nil,
        destination: Binding<ArticleReaderDestination?>,
        @ViewBuilder label: @escaping () -> Label
    ) {
        self.article = article
        self.position = position
        _destination = destination
        self.label = label
    }

    var body: some View {
        Button {
            guard let nextDestination = ArticleReaderCoordinator.open(
                article: article,
                position: position,
                currentDestination: destination,
                markAsRead: BookmarkService.shared.markAsRead,
                logTap: { _, _ in ReadingEventTracker.shared.logTap(article: article) }
            ) else { return }
            HapticService.impact(.light)
            destination = nextDestination
        } label: {
            label()
        }
        .accessibilityHint(accessibilityHint)
    }

    private var accessibilityHint: String {
        switch article.readerRoute {
        case .native:
            return "Opens the article in Daily"
        case .source:
            return "Opens the original publisher website"
        case .unavailable:
            return "Shows the available article information"
        }
    }
}

private struct ArticleReaderRoutingModifier: ViewModifier {
    @Binding var destination: ArticleReaderDestination?

    func body(content: Content) -> some View {
        content
            .navigationDestination(item: navigationArticle) { article in
                ArticleDetailView(article: article, tracksOpenAutomatically: false)
            }
            .sheet(item: sourceDestination) { source in
                SafariView(url: source.url)
                    .ignoresSafeArea()
                    .accessibilityIdentifier("article-source-reader")
            }
    }

    private var navigationArticle: Binding<NewsArticle?> {
        Binding(
            get: { destination?.navigationArticle },
            set: { article in
                guard let article else {
                    if destination?.navigationArticle != nil { destination = nil }
                    return
                }
                destination = .native(article)
            }
        )
    }

    private var sourceDestination: Binding<ArticleSourceDestination?> {
        Binding(
            get: { destination?.sourceDestination },
            set: { source in
                guard let source else {
                    if destination?.sourceDestination != nil { destination = nil }
                    return
                }
                destination = .source(source)
            }
        )
    }
}

extension View {
    func articleReaderDestination(_ destination: Binding<ArticleReaderDestination?>) -> some View {
        modifier(ArticleReaderRoutingModifier(destination: destination))
    }
}
