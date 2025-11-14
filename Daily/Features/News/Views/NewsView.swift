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
        NavigationView {
            ZStack {
                // Show empty state only if no curated articles yet - Apple style
                if viewModel.curatedArticles.isEmpty && !viewModel.isCurating {
                    // Empty state
                    VStack(spacing: AppSpacing.xl) {
                        ZStack {
                            Circle()
                                .fill(BrandColors.primary.opacity(0.08))
                                .frame(width: 80, height: 80)
                            
                            Image(systemName: "newspaper")
                                .font(.system(size: 36, weight: .light))
                                .foregroundColor(BrandColors.primary)
                        }
                        
                        VStack(spacing: AppSpacing.xs) {
                            Text("No articles available")
                                .font(AppTypography.title3)
                                .foregroundColor(BrandColors.textPrimary)
                            
                            if let error = viewModel.errorMessage {
                                Text(error)
                                    .font(AppTypography.subheadline)
                                    .foregroundColor(BrandColors.error)
                                    .multilineTextAlignment(.center)
                                    .padding(.horizontal, AppSpacing.xl)
                            } else {
                                Text("Try refreshing to get the latest news")
                                    .font(AppTypography.subheadline)
                                    .foregroundColor(BrandColors.textSecondary)
                                    .multilineTextAlignment(.center)
                                    .padding(.horizontal, AppSpacing.xl)
                            }
                        }
                        
                        Button(action: {
                            let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                            impactFeedback.impactOccurred()
                            
                            Task {
                                await viewModel.curateNews()
                            }
                        }) {
                            HStack(spacing: AppSpacing.sm) {
                                Image(systemName: "arrow.clockwise")
                                    .font(.system(size: 15, weight: .medium))
                                Text("Get Fresh News")
                                    .font(AppTypography.labelLarge)
                            }
                        }
                        .brandedButton()
                        .padding(.horizontal, AppSpacing.xl)
                        .padding(.top, AppSpacing.md)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(BrandColors.background)
                } else {
                    ScrollView {
                        VStack(spacing: 0) {
                            // Error banner
                            if let error = viewModel.errorMessage, !error.isEmpty {
                                HStack(spacing: AppSpacing.sm) {
                                    Image(systemName: "exclamationmark.triangle.fill")
                                        .foregroundColor(BrandColors.warning)
                                        .font(.system(size: 16))
                                    Text(error)
                                        .font(AppTypography.bodyMedium)
                                        .foregroundColor(BrandColors.textPrimary)
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
                                .background(BrandColors.warning.opacity(0.1))
                                .cornerRadius(AppCornerRadius.medium)
                                .padding(.horizontal, AppSpacing.md)
                                .padding(.top, AppSpacing.sm)
                            }
                            
                            // Curated Articles Section - Apple style
                            if !viewModel.curatedArticles.isEmpty {
                                VStack(alignment: .leading, spacing: AppSpacing.lg) {
                                    // Header - Apple style
                                    HStack(alignment: .top) {
                                        VStack(alignment: .leading, spacing: AppSpacing.xs) {
                                            Text("For you")
                                                .font(AppTypography.title3)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text("\(viewModel.curatedArticles.count) carefully selected articles")
                                                .font(AppTypography.footnote)
                                                .foregroundColor(BrandColors.textSecondary)
                                        }
                                        Spacer()
                                    }
                                    .padding(.horizontal, AppSpacing.md)
                                    .padding(.top, AppSpacing.md)
                                    
                                    // Articles list - Apple style spacing with navigation to detail
                                    ForEach(viewModel.curatedArticles) { article in
                                        NavigationLink(destination: ArticleDetailView(article: article)) {
                                            ArticleCardView(article: article)
                                                .padding(.horizontal, AppSpacing.md)
                                                .padding(.bottom, AppSpacing.sm)
                                        }
                                        .buttonStyle(.plain)
                                    }
                                }
                                .padding(.bottom, AppSpacing.lg)
                            }
                            
                            // Hide regular articles section - we only show headlines and curated articles
                        }
                    }
                    .refreshable {
                        await viewModel.curateNews()
                    }
                }
                
                // Curating loading overlay - Apple style
                if viewModel.isCurating {
                    ZStack {
                        Color.black.opacity(0.3)
                            .ignoresSafeArea()
                        
                        VStack(spacing: AppSpacing.lg) {
                            ProgressView()
                                .scaleEffect(1.2)
                                .tint(BrandColors.primary)
                                .progressViewStyle(CircularProgressViewStyle())
                            
                            VStack(spacing: AppSpacing.xs) {
                                Text("Getting Fresh News")
                                    .foregroundColor(BrandColors.textPrimary)
                                    .font(AppTypography.headline)
                                
                                Text("Finding news articles for you...")
                                    .foregroundColor(BrandColors.textSecondary)
                                    .font(AppTypography.subheadline)
                                    .multilineTextAlignment(.center)
                            }
                        }
                        .padding(AppSpacing.xl)
                        .background(.ultraThinMaterial)
                        .cornerRadius(AppCornerRadius.sheet)
                        .shadow(
                            color: AppShadows.large.color,
                            radius: AppShadows.large.radius,
                            x: AppShadows.large.x,
                            y: AppShadows.large.y
                        )
                        .padding(.horizontal, AppSpacing.xxl)
                    }
                }
            }
            .navigationTitle("Daily")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(action: {
                        let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                        impactFeedback.impactOccurred()
                        
                        Task {
                            await viewModel.curateNews()
                        }
                    }) {
                        HStack(spacing: AppSpacing.xs) {
                            if viewModel.isCurating {
                                ProgressView()
                                    .progressViewStyle(CircularProgressViewStyle(tint: BrandColors.primary))
                                    .scaleEffect(0.7)
                            } else {
                                Image(systemName: "sparkles")
                                    .font(.system(size: 13, weight: .medium))
                            }
                            Text("Get Fresh News")
                                .font(AppTypography.labelSmall)
                        }
                        .foregroundColor(BrandColors.primary)
                        .padding(.horizontal, AppSpacing.sm)
                        .padding(.vertical, AppSpacing.xs)
                        .background(BrandColors.primary.opacity(0.1))
                        .cornerRadius(AppCornerRadius.small)
                    }
                    .disabled(viewModel.isCurating)
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
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
                                    Image(systemName: "person.circle.fill")
                                        .font(.title3)
                                        .foregroundColor(BrandColors.primary)
                                }
                            }
                            .frame(width: 28, height: 28)
                            .clipShape(Circle())
                        } else {
                            Image(systemName: "person.circle.fill")
                                .font(.title3)
                                .foregroundColor(BrandColors.primary)
                        }
                    }
                }
            }
            .sheet(isPresented: $showingProfile) {
                ProfileView()
            }
            // Auto-refresh personalized news after onboarding completes
            .onReceive(NotificationCenter.default.publisher(for: .onboardingCompleted)) { _ in
                Task {
                    await viewModel.curateNews()
                }
            }
        }
    }
}

#Preview {
    NewsView()
}

