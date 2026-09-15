import Foundation

nonisolated extension NewsArticle {
    func hasOfflinePermission(at now: Date = Date()) -> Bool {
        guard verifiedNativeBody != nil, let start = presentation?.validatedAt,
              let end = presentation?.offlineValidUntil else { return false }
        return start <= now && now < end && end.timeIntervalSince(start) <= 86_400
    }
    /// Only a complete native body can identify what was actually displayed as read.
    /// Source-web/analysis previews never prove that the publisher body was read.
    var readContentHash: String? {
        guard presentation?.mode == .nativeFullText, verifiedNativeBody != nil,
              let hash = presentation?.provenance?.contentHash,
              hash.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { return nil }
        return hash
    }

    /// Only a complete, server-stamped card may attribute telemetry to an edition.
    var deliveryReceipt: (requestID: String, position: Int)? {
        guard let feedRequestID, UUID(uuidString: feedRequestID) != nil,
              let deliveryPosition, deliveryPosition >= 0,
              let readerGeneration, readerGeneration > 0,
              let readerRevision, readerRevision > 0 else { return nil }
        return (feedRequestID, deliveryPosition)
    }

    /// Standalone bookmarks/detail caches are not displayed feed cards.
    func withoutFeedReceipt() -> NewsArticle {
        var article = self
        article.feedRequestID = nil
        article.deliveryPosition = nil
        article.readerGeneration = nil
        article.readerRevision = nil
        return article.withoutEventDelivery()
    }

    /// Detail responses are allowed to advance the content version, but never
    /// to substitute a different article or publisher origin.
    func acceptsReaderDetail(_ detail: NewsArticle) -> Bool {
        guard detail.id == id else { return false }

        if let currentOrigin = originalSourceURL,
           let detailOrigin = detail.originalSourceURL,
           !Self.hasSamePublisherOrigin(currentOrigin, detailOrigin) {
            return false
        }

        // An authenticated detail response may revoke native presentation and
        // intentionally omit native provenance. Version monotonicity is only
        // meaningful when the response still claims a native body.
        if detail.presentation?.mode == .nativeFullText {
            // A native detail must carry its own canonical origin and bind its
            // provenance to that publisher. Never let the retained legacy URL
            // satisfy this authenticated-detail check.
            guard let detailCanonicalOrigin = Self.validSourceURL(detail.presentation?.originalURL),
                  let provenanceOrigin = Self.validSourceURL(
                    detail.presentation?.provenance?.sourceURL
                  ),
                  Self.provenanceOriginIsBound(
                    kind: detail.presentation?.provenance?.kind,
                    canonicalURL: detailCanonicalOrigin,
                    provenanceURL: provenanceOrigin
                  ),
                  detail.verifiedNativeBody != nil else {
                return false
            }
            if let originalOrigin = originalSourceURL,
               !Self.hasSamePublisherOrigin(originalOrigin, detailCanonicalOrigin) {
                return false
            }
            if let expectedVersion = presentation?.provenance?.contentVersion {
                guard let detailVersion = detail.presentation?.provenance?.contentVersion,
                      detailVersion >= expectedVersion else {
                    return false
                }
            }
            if let expectedPolicyVersion = presentation?.provenance?.policyVersion {
                guard let detailPolicyVersion = detail.presentation?.provenance?.policyVersion,
                      detailPolicyVersion >= expectedPolicyVersion else {
                    return false
                }
            }
        }
        return true
    }

    /// Merge a detail response without allowing it to rewrite canonical publisher metadata.
    func mergingReaderDetail(_ detail: NewsArticle, at now: Date = Date()) -> NewsArticle {
        let corrected = detail.presentation?.validatedAt != nil
            && (detail.presentation?.provenance?.contentVersion ?? 0) > (presentation?.provenance?.contentVersion ?? 0)
        var merged = NewsArticle(
            id: id,
            title: corrected ? detail.title : title,
            summary: corrected ? detail.summary : (nonEmpty(summary) ?? nonEmpty(detail.summary)),
            content: nil,
            author: nonEmpty(author) ?? nonEmpty(detail.author),
            source: nonEmpty(source) ?? nonEmpty(detail.source),
            imageURL: nonEmpty(imageURL) ?? nonEmpty(detail.imageURL),
            image: image ?? detail.image,
            publishedAt: publishedAt ?? detail.publishedAt,
            category: nonEmpty(category) ?? nonEmpty(detail.category),
            url: nonEmpty(url) ?? nonEmpty(detail.url)
        )
        merged.relevanceScore = relevanceScore
        merged.relevant = relevant
        merged.relevanceReason = relevanceReason
        merged.feedRole = feedRole
        merged.whyThisStory = whyThisStory
        merged.whyNow = whyNow
        merged.matchedProfileSignals = matchedProfileSignals
        merged.clusterID = clusterID
        merged.importanceScore = importanceScore
        // Detail/cache responses never introduce or renew feed authorization.
        merged.eventDelivery = eventDelivery
        merged.readerGeneration = readerGeneration
        merged.readerRevision = readerRevision
        merged.feedRequestID = feedRequestID
        merged.deliveryPosition = deliveryPosition
        merged.bodyExcerpt = nonEmpty(detail.bodyExcerpt) ?? nonEmpty(bodyExcerpt)
        merged.presentation = detail.presentation ?? presentation
        return merged.normalizedForDisplay(at: now)
    }

    /// Persist only text that the presentation contract permits Daily to display.
    /// Legacy `content` is deliberately removed because its origin and completeness are unknown.
    /// Callers must opt in to caching a complete, explicitly permitted native body.
    func safeForReaderCache(includeVerifiedNativeBody: Bool = false) -> NewsArticle {
        var cached = NewsArticle(
            id: id,
            title: title,
            summary: summary,
            content: nil,
            author: author,
            source: source,
            imageURL: imageURL,
            image: image,
            publishedAt: publishedAt,
            category: category,
            url: url
        )
        cached.relevanceScore = relevanceScore
        cached.relevant = relevant
        cached.relevanceReason = relevanceReason
        cached.feedRole = feedRole
        cached.whyThisStory = whyThisStory
        cached.whyNow = whyNow
        cached.matchedProfileSignals = matchedProfileSignals
        cached.clusterID = clusterID
        cached.importanceScore = importanceScore
        cached.eventDelivery = eventDelivery
        cached.readerGeneration = readerGeneration
        cached.readerRevision = readerRevision
        cached.feedRequestID = feedRequestID
        cached.deliveryPosition = deliveryPosition
        cached.bodyExcerpt = bodyExcerpt

        if let presentation {
            cached.presentation = ArticlePresentation(
                mode: presentation.mode,
                originalURL: presentation.originalURL,
                body: includeVerifiedNativeBody ? verifiedNativeBody : nil,
                bodyState: presentation.bodyState,
                accessHint: presentation.accessHint,
                reason: presentation.reason,
                provenance: presentation.provenance,
                offlineValidUntil: presentation.offlineValidUntil,
                validatedAt: presentation.validatedAt
            )
        }
        return cached.withoutEventDelivery()
    }

    /// A cached detail can satisfy a body-less feed row only when the server's
    /// current contract still permits native reading and its version is not stale.
    func mergingCompatibleCachedDetail(_ cachedDetail: NewsArticle?) -> NewsArticle? {
        guard readerRoute == .native,
              let cachedDetail,
              cachedDetail.id == id,
              acceptsReaderDetail(cachedDetail),
              cachedDetail.verifiedNativeBody != nil else {
            return nil
        }

        guard let expectedVersion = presentation?.provenance?.contentVersion,
              let cachedVersion = cachedDetail.presentation?.provenance?.contentVersion,
              cachedVersion == expectedVersion,
              let expectedPolicyVersion = presentation?.provenance?.policyVersion,
              let cachedPolicyVersion = cachedDetail.presentation?.provenance?.policyVersion,
              cachedPolicyVersion == expectedPolicyVersion else {
            // Old servers did not include an explicit version in feed rows.
            // Reusing a cached publisher body in that state could resurrect
            // text after a policy change, so fail closed and fetch detail.
            return nil
        }

        if let currentHost = originalSourceURL?.host?.lowercased(),
           let cachedHost = cachedDetail.originalSourceURL?.host?.lowercased(),
           currentHost != cachedHost {
            return nil
        }

        let merged = mergingReaderDetail(cachedDetail)
        return merged.verifiedNativeBody == nil ? nil : merged
    }

    private func nonEmpty(_ value: String?) -> String? {
        guard let value = value?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty else {
            return nil
        }
        return value
    }
}
