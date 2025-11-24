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
                    VStack(spacing: AppSpacing.xl) {
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
            
            Text(heroSubtitle)
                .font(AppTypography.bodyMedium)
                .foregroundColor(.white.opacity(0.85))
            
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
                    .padding(.vertical, AppSpacing.sm)
                    .background(.white.opacity(0.18))
                    .foregroundColor(.white)
                    .clipShape(Capsule())
                }
                .disabled(viewModel.isCurating)
                
                if viewModel.curatedArticles.count > 0 {
                    Text("\(viewModel.curatedArticles.count) stories ready")
                        .font(AppTypography.caption1)
                        .foregroundColor(.white.opacity(0.8))
                        .padding(.horizontal, AppSpacing.md)
                        .padding(.vertical, AppSpacing.xs)
                        .background(.white.opacity(0.12))
                        .clipShape(Capsule())
                }
                
                Spacer()
            }
        }
        .padding(AppSpacing.lg)
        .background(
            LinearGradient(
                colors: [BrandColors.primary, BrandColors.primaryDark],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .cornerRadius(AppCornerRadius.xlarge)
        .shadow(color: BrandColors.primary.opacity(0.25), radius: 30, x: 0, y: 20)
    }
    
    var emptyStateCard: some View {
        VStack(spacing: AppSpacing.lg) {
            Image(systemName: "rectangle.and.text.magnifyingglass")
                .font(.system(size: 42, weight: .light))
                .foregroundColor(BrandColors.primary)
                .padding()
                .background(BrandColors.primary.opacity(0.08))
                .clipShape(Circle())
            
            VStack(spacing: AppSpacing.sm) {
                Text("No articles yet")
                    .font(AppTypography.title3)
                    .foregroundColor(BrandColors.textPrimary)
                
                Text(viewModel.errorMessage ?? "Tap the button above to curate a fresh Apple-style briefing.")
                    .font(AppTypography.subheadline)
                    .foregroundColor(viewModel.errorMessage == nil ? BrandColors.textSecondary : BrandColors.error)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(AppSpacing.xl)
        .glassCard()
    }
    
    func errorBanner(_ message: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(BrandColors.warning)
            Text(message)
                .font(AppTypography.bodyMedium)
                .foregroundColor(BrandColors.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button("Dismiss") {
                withAnimation {
                    viewModel.errorMessage = nil
                }
            }
            .font(AppTypography.labelSmall)
            .foregroundColor(BrandColors.warning)
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
                    }
                    .padding(.horizontal, AppSpacing.sm)
                    .padding(.vertical, AppSpacing.xs)
                    .background(BrandColors.primary.opacity(0.12))
                    .foregroundColor(BrandColors.primary)
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
                .background(BrandColors.secondaryBackground.opacity(0.6))
                .cornerRadius(AppCornerRadius.medium)
            }
            
            VStack(spacing: AppSpacing.md) {
                ForEach(viewModel.curatedArticles) { article in
                    NavigationLink(destination: ArticleDetailView(article: article)) {
                        ArticleCardView(article: article)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
    
    var curatingOverlay: some View {
        ZStack {
            Color.black.opacity(0.35)
                .ignoresSafeArea()
            
            VStack(spacing: AppSpacing.lg) {
                ProgressView()
                    .scaleEffect(1.2)
                    .tint(BrandColors.primary)
                
                Text("Curating your briefing")
                    .font(AppTypography.headline)
                    .foregroundColor(BrandColors.textPrimary)
                
                Text("Feel free to close the app. We’ll notify you when the stories are ready.")
                    .font(AppTypography.body)
                    .foregroundColor(BrandColors.textSecondary)
                    .multilineTextAlignment(.center)
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
                }
                .padding(.horizontal, AppSpacing.md)
                .padding(.vertical, AppSpacing.xs)
                .background(BrandColors.cardBackground.opacity(0.9))
                .clipShape(Capsule())
                .shadow(color: Color.black.opacity(0.1), radius: 8, x: 0, y: 4)
            }
            .disabled(viewModel.isCurating)
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

