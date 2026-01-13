//
//  NewsArticle+Normalization.swift
//  Daily
//
//  Normalizes article text so UI layout and paragraph wrapping are consistent.
//  Some sources return "hard-wrapped" content with single newlines every ~60-80 chars,
//  NBSPs, and other whitespace that changes wrapping behavior and can even cause overflow.
//

import Foundation

extension NewsArticle {
    /// Returns a copy of the article with normalized text fields for deterministic rendering.
    func normalizedForDisplay() -> NewsArticle {
        NewsArticle(
            id: id,
            title: ArticleTextNormalizer.normalizeInline(title),
            summary: summary.map { ArticleTextNormalizer.normalizeInline($0) },
            content: content.map { ArticleTextNormalizer.normalizeBody($0) },
            author: author?.trimmingCharacters(in: .whitespacesAndNewlines),
            source: source?.trimmingCharacters(in: .whitespacesAndNewlines),
            imageURL: imageURL,
            publishedAt: publishedAt,
            category: category?.trimmingCharacters(in: .whitespacesAndNewlines),
            url: url
        )
    }
}

/// Central text normalization rules for article content.
enum ArticleTextNormalizer {
    /// For titles / summaries (single-block text).
    static func normalizeInline(_ input: String) -> String {
        let base = normalizeCommonWhitespace(input)
        // Inline text shouldn't contain hard line breaks; convert them to spaces.
        let unwrapped = unwrapHardLineBreaks(base)
        return collapseSpaces(unwrapped).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// For article bodies (multi-paragraph text).
    static func normalizeBody(_ input: String) -> String {
        var text = input

        // Remove typical NewsAPI suffix like: " [+2095 chars]"
        if let range = text.range(of: #"\s*\[\+\d+\s+chars\]"#, options: .regularExpression) {
            text.removeSubrange(range)
        }

        text = normalizeCommonWhitespace(text)

        // Normalize newlines
        text = text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")

        // Ensure paragraph breaks are consistent
        text = text.replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)

        // Unwrap single newlines inside paragraphs (common in scraped content)
        text = unwrapHardLineBreaks(text)

        // Re-normalize paragraph breaks after unwrapping
        text = text.replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)

        // Trim whitespace around paragraph breaks and collapse extra spaces
        let paragraphs = text
            .components(separatedBy: "\n\n")
            .map { collapseSpaces($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        return paragraphs.joined(separator: "\n\n")
    }

    // MARK: - Internals

    /// Normalizes whitespace that affects wrapping/measurement (NBSP, tabs, zero-width spaces).
    private static func normalizeCommonWhitespace(_ input: String) -> String {
        input
            .replacingOccurrences(of: "\\n", with: "\n")          // backend sometimes double-escapes
            .replacingOccurrences(of: "\u{00A0}", with: " ")      // NO-BREAK SPACE
            .replacingOccurrences(of: "\u{202F}", with: " ")      // NARROW NO-BREAK SPACE
            .replacingOccurrences(of: "\u{2007}", with: " ")      // FIGURE SPACE
            .replacingOccurrences(of: "\u{200B}", with: "")       // ZERO WIDTH SPACE
            .replacingOccurrences(of: "\t", with: " ")
    }

    /// Converts "hard-wrapped" single newlines to spaces while preserving paragraph breaks.
    /// Strategy:
    /// - Temporarily mark paragraph breaks (\n\n+)
    /// - Replace remaining \n with a space
    /// - Restore paragraph breaks
    private static func unwrapHardLineBreaks(_ input: String) -> String {
        let marker = "\u{E000}" // private-use marker unlikely to appear in content

        var text = input
        text = text.replacingOccurrences(of: #"\n{2,}"#, with: marker, options: .regularExpression)
        text = text.replacingOccurrences(of: "\n", with: " ")
        text = text.replacingOccurrences(of: marker, with: "\n\n")
        return text
    }

    private static func collapseSpaces(_ input: String) -> String {
        input.replacingOccurrences(of: #"[ ]{2,}"#, with: " ", options: .regularExpression)
    }
}


