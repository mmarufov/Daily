//
//  ArticleBodyTextView.swift
//  Daily
//
//  Renders long-form article text with deterministic wrapping.
//  SwiftUI `Text` will not break very long, unbroken tokens (URLs, NBSP runs),
//  which can cause horizontal overflow. This view forces char-wrapping.
//

import SwiftUI
import UIKit

struct ArticleBodyTextView: UIViewRepresentable {
    let text: String
    var lineSpacing: CGFloat = 6
    var fontSizeMultiplier: CGFloat = 1.0

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false
        view.isSelectable = false
        view.isScrollEnabled = false
        view.backgroundColor = .clear
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.textContainer.lineBreakMode = .byCharWrapping
        view.adjustsFontForContentSizeCategory = true

        // Let SwiftUI constrain the width; avoid expanding horizontally.
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)

        return view
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        uiView.attributedText = makeAttributedText(text: text)
    }

    private func makeAttributedText(text: String) -> NSAttributedString {
        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.alignment = .natural
        paragraphStyle.lineSpacing = lineSpacing
        paragraphStyle.lineBreakMode = .byCharWrapping

        return NSAttributedString(
            string: text,
            attributes: [
                .font: articleBodyUIFont(),
                .foregroundColor: UIColor(BrandColors.textPrimary),
                .paragraphStyle: paragraphStyle
            ]
        )
    }

    private func articleBodyUIFont() -> UIFont {
        let fontSize = 19 * fontSizeMultiplier
        let base = UIFont.systemFont(ofSize: fontSize, weight: .regular)
        let designed = base.fontDescriptor.withDesign(.serif).map { UIFont(descriptor: $0, size: fontSize) } ?? base
        return UIFontMetrics(forTextStyle: .body).scaledFont(for: designed)
    }
}


