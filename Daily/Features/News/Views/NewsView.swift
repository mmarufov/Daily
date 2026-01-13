//
//  NewsView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI
import UIKit

struct NewsView: View {
    @StateObject private var viewModel = NewsViewModel()
    @ObservedObject private var auth = AuthService.shared
    @State private var showingProfile = false
    
    var body: some View {
        NavigationStack {
            ZStack {
                AppleBackgroundView()
                
                ScrollView(.vertical, showsIndicators: false) {
                    LazyVStack(alignment: .leading, spacing: AppSpacing.xl) {
                        heroHeader
                        
                        if viewModel.curatedArticles.isEmpty && !viewModel.isCurating {
                            emptyStateCard
                        } else {
                            if let error = viewModel.errorMessage, !error.isEmpty {
                                errorBanner(error)
                            }
                            
                            curatedSection
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.vertical, AppSpacing.lg)
                }
                
                if viewModel.isCurating {
                    curatingOverlay
                }
            }
            .navigationTitle("Daily")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.light, for: .navigationBar)
            .toolbar {
                toolbarContent
            }
            .sheet(isPresented: $showingProfile) {
                ProfileView()
            }
        }
    }
}

// MARK: - Private builders

private extension NewsView {
    var heroHeader: some View {
        VStack(alignment: .leading, spacing: AppSpacing.md) {
            Text(greetingTitle)
                .font(AppTypography.title2)
                .foregroundColor(.white)
                .shadow(color: .black.opacity(0.1), radius: 2, x: 0, y: 1)
            
            Text(heroSubtitle)
                .font(AppTypography.bodyMedium)
                .foregroundColor(.white.opacity(0.9))
            
            HStack(spacing: AppSpacing.sm) {
                Button(action: {
                    let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                    impactFeedback.impactOccurred()
                    Task { await viewModel.curateNews() }
                }) {
                    HStack(spacing: AppSpacing.xs) {
                        if viewModel.isCurating {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                .scaleEffect(0.8)
                        } else {
                            Image(systemName: "sparkles")
                                .font(.system(size: 14, weight: .semibold))
                        }
                        Text(viewModel.isCurating ? "Working..." : "Get Fresh News")
                            .font(AppTypography.labelMedium)
                            .fontWeight(.semibold)
                    }
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.vertical, AppSpacing.sm + 2)
                    .background(
                        ZStack {
                            Capsule()
                                .fill(.white.opacity(0.25))
                            Capsule()
                                .fill(.white.opacity(0.1))
                                .blur(radius: 10)
                        }
                    )
                    .foregroundColor(.white)
                    .overlay(
                        Capsule()
                            .stroke(.white.opacity(0.3), lineWidth: 1)
                    )
                    .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 4)
                }
                .disabled(viewModel.isCurating)
                .scaleEffect(viewModel.isCurating ? 0.98 : 1.0)
                .animation(.easeInOut(duration: 0.2), value: viewModel.isCurating)
                
                if viewModel.curatedArticles.count > 0 {
                    Text("\(viewModel.curatedArticles.count) stories ready")
                        .font(AppTypography.caption1)
                        .fontWeight(.medium)
                        .foregroundColor(.white.opacity(0.9))
                        .padding(.horizontal, AppSpacing.md)
                        .padding(.vertical, AppSpacing.xs + 2)
                        .background(.white.opacity(0.15))
                        .overlay(
                            Capsule()
                                .stroke(.white.opacity(0.25), lineWidth: 1)
                        )
                        .clipShape(Capsule())
                }
                
                Spacer()
            }
        }
        .padding(AppSpacing.lg)
        .background(
            ZStack {
                LinearGradient(
                    colors: [BrandColors.primary, BrandColors.primaryDark],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                
                // Add subtle texture overlay
                RadialGradient(
                    colors: [
                        .white.opacity(0.1),
                        .clear
                    ],
                    center: .topLeading,
                    startRadius: 0,
                    endRadius: 200
                )
            }
        )
        .cornerRadius(AppCornerRadius.xlarge)
        .overlay(
            RoundedRectangle(cornerRadius: AppCornerRadius.xlarge)
                .stroke(
                    LinearGradient(
                        colors: [
                            .white.opacity(0.2),
                            .white.opacity(0.05)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 1
                )
        )
        .frame(maxWidth: .infinity, alignment: .leading)
        .shadow(color: BrandColors.primary.opacity(0.3), radius: 30, x: 0, y: 20)
        .shadow(color: .black.opacity(0.1), radius: 10, x: 0, y: 5)
    }
    
    var emptyStateCard: some View {
        VStack(spacing: AppSpacing.lg) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [
                                BrandColors.primary.opacity(0.12),
                                BrandColors.primary.opacity(0.06)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 80, height: 80)
                
                Image(systemName: "rectangle.and.text.magnifyingglass")
                    .font(.system(size: 36, weight: .light))
                    .foregroundColor(BrandColors.primary)
            }
            
            VStack(spacing: AppSpacing.sm) {
                Text("No articles yet")
                    .font(AppTypography.title3)
                    .foregroundColor(BrandColors.textPrimary)
                
                Text(viewModel.errorMessage ?? "Tap the button above to curate a fresh Apple-style briefing.")
                    .font(AppTypography.subheadline)
                    .foregroundColor(viewModel.errorMessage == nil ? BrandColors.textSecondary : BrandColors.error)
                    .multilineTextAlignment(.center)
                    .lineSpacing(2)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(AppSpacing.xl)
        .glassCard()
    }
    
    func errorBanner(_ message: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            ZStack {
                Circle()
                    .fill(BrandColors.warning.opacity(0.15))
                    .frame(width: 32, height: 32)
                
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(BrandColors.warning)
            }
            
            Text(message)
                .font(AppTypography.bodyMedium)
                .foregroundColor(BrandColors.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            
            Spacer()
            
            Button("Dismiss") {
                let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                impactFeedback.impactOccurred()
                withAnimation {
                    viewModel.errorMessage = nil
                }
            }
            .font(AppTypography.labelSmall)
            .fontWeight(.medium)
            .foregroundColor(BrandColors.warning)
            .padding(.horizontal, AppSpacing.sm)
            .padding(.vertical, AppSpacing.xs)
            .background(BrandColors.warning.opacity(0.1))
            .clipShape(Capsule())
        }
        .padding(AppSpacing.md)
        .glassCard(cornerRadius: AppCornerRadius.large)
    }
    
    var curatedSection: some View {
        VStack(alignment: .leading, spacing: AppSpacing.lg) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: AppSpacing.xs) {
                    Text("Curated for you")
                        .font(AppTypography.title3)
                        .foregroundColor(BrandColors.textPrimary)
                    Text("Handpicked to match your interests")
                        .font(AppTypography.footnote)
                        .foregroundColor(BrandColors.textSecondary)
                }
                Spacer()
                Button(action: {
                    let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                    impactFeedback.impactOccurred()
                    Task { await viewModel.prepareAllArticles() }
                }) {
                    HStack(spacing: AppSpacing.xs) {
                        if viewModel.isPreparingArticles {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: BrandColors.primary))
                                .scaleEffect(0.7)
                        } else {
                            Image(systemName: "bolt.fill")
                                .font(.system(size: 13, weight: .medium))
                        }
                        Text(viewModel.isPreparingArticles ? "Preparing…" : "Preload")
                            .font(AppTypography.labelSmall)
                            .fontWeight(.medium)
                    }
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.xs + 2)
                    .background(
                        ZStack {
                            Capsule()
                                .fill(BrandColors.primary.opacity(0.12))
                            Capsule()
                                .fill(BrandColors.primary.opacity(0.06))
                                .blur(radius: 8)
                        }
                    )
                    .foregroundColor(BrandColors.primary)
                    .overlay(
                        Capsule()
                            .stroke(BrandColors.primary.opacity(0.2), lineWidth: 1)
                    )
                    .clipShape(Capsule())
                }
                .disabled(viewModel.isPreparingArticles)
            }
            
            if let status = viewModel.preparationStatus {
                HStack(spacing: AppSpacing.sm) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(BrandColors.success)
                        .font(.system(size: 14))
                    Text(status)
                        .font(AppTypography.footnote)
                        .foregroundColor(BrandColors.textSecondary)
                    Spacer()
                }
                .padding(.horizontal, AppSpacing.md)
                .padding(.vertical, AppSpacing.sm)
                .background(
                    ZStack {
                        RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                            .fill(BrandColors.success.opacity(0.08))
                        RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                            .fill(BrandColors.secondaryBackground.opacity(0.4))
                    }
                )
                .overlay(
                    RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                        .stroke(BrandColors.success.opacity(0.15), lineWidth: 1)
                )
            }
            
            VStack(spacing: AppSpacing.md + 4) {
                ForEach(viewModel.curatedArticles) { article in
                    NavigationLink(destination: ArticleDetailView(article: article)) {
                        ArticleCardView(article: article)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
    
    var curatingOverlay: some View {
        ZStack {
            Color.black.opacity(0.4)
                .ignoresSafeArea()
            
            VStack(spacing: AppSpacing.lg) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [
                                    BrandColors.primary.opacity(0.15),
                                    BrandColors.primary.opacity(0.08)
                                ],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .frame(width: 80, height: 80)
                    
                    ProgressView()
                        .scaleEffect(1.3)
                        .tint(BrandColors.primary)
                }
                
                VStack(spacing: AppSpacing.sm) {
                    Text("Curating your briefing")
                        .font(AppTypography.headline)
                        .foregroundColor(BrandColors.textPrimary)
                    
                    Text("Feel free to close the app. We'll notify you when the stories are ready.")
                        .font(AppTypography.body)
                        .foregroundColor(BrandColors.textSecondary)
                        .multilineTextAlignment(.center)
                        .lineSpacing(2)
                }
            }
            .padding(AppSpacing.xl)
            .glassCard(cornerRadius: AppCornerRadius.sheet)
            .padding(.horizontal, AppSpacing.xxl)
        }
    }
    
    @ToolbarContentBuilder
    var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .navigationBarLeading) {
            Button(action: {
                showingProfile = true
            }) {
                if let photoURL = auth.currentUser?.photo_url,
                   let url = URL(string: photoURL) {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image
                                .resizable()
                                .aspectRatio(contentMode: .fill)
                        default:
                            Image(systemName: "person.crop.circle.fill")
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .foregroundColor(.white)
                        }
                    }
                    .frame(width: 32, height: 32)
                    .clipShape(Circle())
                } else {
                    Image(systemName: "person.crop.circle.fill")
                        .font(.system(size: 28))
                        .foregroundColor(.white)
                }
            }
        }
        
        ToolbarItem(placement: .navigationBarTrailing) {
            Button(action: {
                let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                impactFeedback.impactOccurred()
                Task { await viewModel.curateNews() }
            }) {
                HStack(spacing: AppSpacing.xs) {
                    if viewModel.isCurating {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: BrandColors.primary))
                            .scaleEffect(0.7)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 13, weight: .medium))
                    }
                    Text(viewModel.isCurating ? "Refreshing" : "Refresh")
                        .font(AppTypography.labelSmall)
                        .fontWeight(.medium)
                }
                .padding(.horizontal, AppSpacing.md)
                .padding(.vertical, AppSpacing.xs + 2)
                .background(
                    ZStack {
                        Capsule()
                            .fill(BrandColors.cardBackground.opacity(0.95))
                        Capsule()
                            .fill(.white.opacity(0.3))
                            .blur(radius: 10)
                    }
                )
                .overlay(
                    Capsule()
                        .stroke(Color.black.opacity(0.06), lineWidth: 0.5)
                )
                .clipShape(Capsule())
                .shadow(color: Color.black.opacity(0.08), radius: 8, x: 0, y: 4)
            }
            .disabled(viewModel.isCurating)
            .scaleEffect(viewModel.isCurating ? 0.98 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: viewModel.isCurating)
        }
    }
    
    var greetingTitle: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 5..<12:
            return "Good morning"
        case 12..<17:
            return "Good afternoon"
        case 17..<22:
            return "Good evening"
        default:
            return "Hello"
        }
    }
    
    var heroSubtitle: String {
        if let date = viewModel.lastCuratedFetchDate {
            let formatter = RelativeDateTimeFormatter()
            formatter.unitsStyle = .short
            let relative = formatter.localizedString(for: date, relativeTo: Date())
            return "Last refreshed \(relative)"
        } else {
            return "Tap refresh to build your briefing"
        }
    }
}

#Preview {
    NewsView()
}

