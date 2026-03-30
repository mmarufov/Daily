//
//  LegacyChatBubbleView.swift
//  Daily
//

import SwiftUI

struct ChatBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .bottom, spacing: AppSpacing.sm) {
            if message.isUser {
                Spacer(minLength: 50)
            }

            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                if message.isUser {
                    Text(message.content)
                        .font(AppTypography.body)
                        .foregroundColor(.white)
                        .padding(.horizontal, AppSpacing.md)
                        .padding(.vertical, AppSpacing.smPlus)
                        .background(BrandColors.primary)
                        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
                } else {
                    Text(message.content)
                        .font(AppTypography.body)
                        .foregroundColor(BrandColors.textPrimary)
                        .padding(.horizontal, AppSpacing.md)
                        .padding(.vertical, AppSpacing.smPlus)
                        .background(Color(.secondarySystemGroupedBackground))
                        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
                }

                Text(message.timestamp, style: .time)
                    .font(AppTypography.caption2)
                    .foregroundColor(BrandColors.textTertiary)
                    .padding(.horizontal, AppSpacing.xs)
            }

            if !message.isUser {
                Spacer(minLength: 50)
            }
        }
    }
}
