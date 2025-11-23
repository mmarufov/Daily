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
                BrandColors.background
                    .ignoresSafeArea(edges: [])
                
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
                                .padding(.horizontal, AppSpacing.lg)
                                .padding(.top, AppSpacing.sm)
                            }
                            
                            // Curated Articles Section - Apple style
                            if !viewModel.curatedArticles.isEmpty {
                                VStack(alignment: .leading, spacing: AppSpacing.lg) {
                                    // Header - Apple style
                                    HStack(alignment: .top, spacing: AppSpacing.sm) {
                                        VStack(alignment: .leading, spacing: AppSpacing.xs) {
                                            Text("For you")
                                                .font(AppTypography.title3)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text("\(viewModel.curatedArticles.count) carefully selected articles")
                                                .font(AppTypography.footnote)
                                                .foregroundColor(BrandColors.textSecondary)
                                                .fixedSize(horizontal: false, vertical: true)
                                        }
                                        .frame(minWidth: 0, maxWidth: .infinity, alignment: .leading)
                                        
                                        // Prepare Articles Button
                                        Button(action: {
                                            let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                                            impactFeedback.impactOccurred()
                                            
                                            Task {
                                                await viewModel.prepareAllArticles()
                                            }
                                        }) {
                                            HStack(spacing: AppSpacing.xs) {
                                                if viewModel.isPreparingArticles {
                                                    ProgressView()
                                                        .progressViewStyle(CircularProgressViewStyle(tint: BrandColors.primary))
                                                        .scaleEffect(0.7)
                                                } else {
                                                    Image(systemName: "bolt.fill")
                                                        .font(.system(size: 12, weight: .medium))
                                                }
                                                Text(viewModel.isPreparingArticles ? "Preparing..." : "Prepare All")
                                                    .font(AppTypography.labelSmall)
                                                    .lineLimit(1)
                                                    .minimumScaleFactor(0.8)
                                            }
                                            .foregroundColor(BrandColors.primary)
                                            .padding(.horizontal, AppSpacing.sm)
                                            .padding(.vertical, AppSpacing.xs)
                                            .background(BrandColors.primary.opacity(0.1))
                                            .cornerRadius(AppCornerRadius.small)
                                        }
                                        .disabled(viewModel.isPreparingArticles)
                                    }
                                    .padding(.horizontal, AppSpacing.lg)
                                    .padding(.top, AppSpacing.md)
                                    
                                    // Preparation status message
                                    if let status = viewModel.preparationStatus {
                                        HStack(spacing: AppSpacing.sm) {
                                            Image(systemName: "checkmark.circle.fill")
                                                .foregroundColor(BrandColors.success)
                                                .font(.system(size: 14))
                                            Text(status)
                                                .font(AppTypography.footnote)
                                                .foregroundColor(BrandColors.textSecondary)
                                                .fixedSize(horizontal: false, vertical: true)
                                        }
                                        .padding(.horizontal, AppSpacing.lg)
                                        .padding(.top, AppSpacing.xs)
                                    }
                                    
                                    // Articles list - Apple style spacing with navigation to detail
                                    ForEach(viewModel.curatedArticles) { article in
                                        NavigationLink(destination: ArticleDetailView(article: article)) {
                                            ArticleCardView(article: article)
                                                .padding(.horizontal, AppSpacing.lg)
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
                    .safeAreaInset(edge: .bottom) {
                        Color.clear.frame(height: 0)
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
                            
                            VStack(spacing: AppSpacing.md) {
                                Text("Getting Fresh News")
                                    .foregroundColor(BrandColors.textPrimary)
                                    .font(AppTypography.headline)
                                
                                VStack(spacing: AppSpacing.xs) {
                                    Text("Finding news articles for you...")
                                        .foregroundColor(BrandColors.textSecondary)
                                        .font(AppTypography.subheadline)
                                        .multilineTextAlignment(.center)
                                    
                                    Text("You can leave the app and come back later to see your personalized news")
                                        .foregroundColor(BrandColors.textSecondary)
                                        .font(AppTypography.footnote)
                                        .multilineTextAlignment(.center)
                                        .padding(.top, AppSpacing.xs)
                                }
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
        }
        .navigationViewStyle(.stack)
    }
}

#Preview {
    NewsView()
}

