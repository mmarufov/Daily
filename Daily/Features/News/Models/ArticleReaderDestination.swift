import Foundation

struct ArticleSourceDestination: Identifiable, Hashable {
    let articleID: String
    let url: URL

    var id: String { "\(articleID)|\(url.absoluteString)" }
}

enum ArticleReaderDestination: Identifiable, Hashable {
    case native(NewsArticle)
    case source(ArticleSourceDestination)
    case unavailable(NewsArticle)

    init(article: NewsArticle) {
        switch article.readerRoute {
        case .native:
            self = .native(article)
        case .source(let url):
            self = .source(ArticleSourceDestination(articleID: article.id, url: url))
        case .unavailable:
            self = .unavailable(article)
        }
    }

    var id: String {
        switch self {
        case .native(let article):
            return "native|\(article.id)"
        case .source(let destination):
            return "source|\(destination.id)"
        case .unavailable(let article):
            return "unavailable|\(article.id)"
        }
    }

    var navigationArticle: NewsArticle? {
        switch self {
        case .native(let article), .unavailable(let article):
            return article
        case .source:
            return nil
        }
    }

    var sourceDestination: ArticleSourceDestination? {
        guard case .source(let destination) = self else { return nil }
        return destination
    }
}

enum ArticleReaderCoordinator {
    /// Returns nil when a destination is already active. Tracking is performed
    /// inside the same gate so rapid repeated taps cannot double-count an open.
    static func open(
        article: NewsArticle,
        position: Int?,
        currentDestination: ArticleReaderDestination?,
        markAsRead: (String) -> Void,
        logTap: (String, Int?) -> Void
    ) -> ArticleReaderDestination? {
        guard currentDestination == nil else { return nil }
        markAsRead(article.id)
        logTap(article.id, position)
        return ArticleReaderDestination(article: article)
    }
}
