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
                // Show topic selection if no topic is selected - Apple style
                if viewModel.selectedTopic == nil {
                    VStack(spacing: AppSpacing.xl) {
                        ZStack {
                            Circle()
                                .fill(BrandColors.primary)
                                .frame(width: 80, height: 80)
                                .shadow(color: BrandColors.primary.opacity(0.15), radius: 12, x: 0, y: 4)
                            
                            Image(systemName: "newspaper.fill")
                                .font(.system(size: 36, weight: .medium))
                                .foregroundColor(.white)
                        }
                        
                        VStack(spacing: AppSpacing.xs) {
                            Text("Choose a Topic")
                                .font(AppTypography.title2)
                                .foregroundColor(BrandColors.textPrimary)
                            
                            Text("Select a topic to see curated news")
                                .font(AppTypography.subheadline)
                                .foregroundColor(BrandColors.textSecondary)
                                .multilineTextAlignment(.center)
                        }
                        .padding(.horizontal, AppSpacing.xl)
                        
                        VStack(spacing: AppSpacing.sm) {
                            ForEach(NewsTopic.allCases, id: \.self) { topic in
                                Button(action: {
                                    let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                                    impactFeedback.impactOccurred()
                                    
                                    withAnimation(.spring(response: 0.35, dampingFraction: 0.75)) {
                                        viewModel.selectTopic(topic)
                                    }
                                    Task {
                                        await viewModel.curateNews()
                                    }
                                }) {
                                    HStack(spacing: AppSpacing.md) {
                                        ZStack {
                                            RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                                                .fill(BrandColors.primary.opacity(0.1))
                                                .frame(width: 40, height: 40)
                                            
                                            Image(systemName: topic.iconName)
                                                .font(.system(size: 18, weight: .medium))
                                                .foregroundColor(BrandColors.primary)
                                        }
                                        
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(topic.displayName)
                                                .font(AppTypography.headline)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text(topic.description)
                                                .font(AppTypography.footnote)
                                                .foregroundColor(BrandColors.textSecondary)
                                        }
                                        
                                        Spacer()
                                        
                                        Image(systemName: "chevron.right")
                                            .font(.system(size: 13, weight: .medium))
                                            .foregroundColor(BrandColors.textTertiary)
                                    }
                                    .padding(AppSpacing.md)
                                    .background(BrandColors.cardBackground)
                                    .cornerRadius(AppCornerRadius.card)
                                    .shadow(
                                        color: AppShadows.card.color,
                                        radius: AppShadows.card.radius,
                                        x: AppShadows.card.x,
                                        y: AppShadows.card.y
                                    )
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal, AppSpacing.lg)
                        .padding(.top, AppSpacing.lg)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(BrandColors.background)
                }
                // Show empty state only if topic is selected but no articles - Apple style
                else if viewModel.curatedArticles.isEmpty && !viewModel.isCurating {
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
                } else if viewModel.selectedTopic != nil {
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
                            if !viewModel.curatedArticles.isEmpty, let topic = viewModel.selectedTopic {
                                VStack(alignment: .leading, spacing: AppSpacing.lg) {
                                    // Header - Apple style
                                    HStack(alignment: .top) {
                                        VStack(alignment: .leading, spacing: AppSpacing.xs) {
                                            Text("\(topic.displayName) News")
                                                .font(AppTypography.title3)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text("\(viewModel.curatedArticles.count) carefully selected articles")
                                                .font(AppTypography.footnote)
                                                .foregroundColor(BrandColors.textSecondary)
                                        }
                                        Spacer()
                                        
                                        // Topic selector button - Apple style
                                        Menu {
                                            ForEach(NewsTopic.allCases, id: \.self) { otherTopic in
                                                Button(action: {
                                                    withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                                                        viewModel.selectTopic(otherTopic)
                                                    }
                                                    Task {
                                                        await viewModel.curateNews()
                                                    }
                                                }) {
                                                    HStack {
                                                        Text(otherTopic.displayName)
                                                        if otherTopic == topic {
                                                            Image(systemName: "checkmark")
                                                                .foregroundColor(BrandColors.primary)
                                                        }
                                                    }
                                                }
                                            }
                                        } label: {
                                            Image(systemName: "ellipsis.circle")
                                                .font(.system(size: 18, weight: .regular))
                                                .foregroundColor(BrandColors.primary)
                                        }
                                    }
                                    .padding(.horizontal, AppSpacing.md)
                                    .padding(.top, AppSpacing.md)
                                    
                                    // Articles list - Apple style spacing
                                    ForEach(viewModel.curatedArticles) { article in
                                        ArticleCardView(article: article)
                                            .padding(.horizontal, AppSpacing.md)
                                            .padding(.bottom, AppSpacing.sm)
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
                                
                                if let topic = viewModel.selectedTopic {
                                    Text("Finding \(topic.displayName) news articles...")
                                        .foregroundColor(BrandColors.textSecondary)
                                        .font(AppTypography.subheadline)
                                        .multilineTextAlignment(.center)
                                } else {
                                    Text("Finding news articles...")
                                        .foregroundColor(BrandColors.textSecondary)
                                        .font(AppTypography.subheadline)
                                        .multilineTextAlignment(.center)
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
            // Don't load anything on initial load - articles only appear after button is pressed
        }
    }
}

#Preview {
    NewsView()
}

