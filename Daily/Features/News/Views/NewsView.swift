//
//  NewsView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

struct NewsView: View {
    @StateObject private var viewModel = NewsViewModel()
    @ObservedObject private var auth = AuthService.shared
    @State private var showingProfile = false
    
    var body: some View {
        NavigationView {
            ZStack {
                // Show topic selection if no topic is selected
                if viewModel.selectedTopic == nil {
                    VStack(spacing: AppSpacing.lg) {
                        ZStack {
                            Circle()
                                .fill(AppGradients.primary)
                                .frame(width: 100, height: 100)
                                .shadow(color: BrandColors.primary.opacity(0.2), radius: 15, x: 0, y: 8)
                            
                            Image(systemName: "newspaper.fill")
                                .font(.system(size: 45, weight: .bold))
                                .foregroundColor(.white)
                        }
                        
                        VStack(spacing: AppSpacing.sm) {
                            Text("Choose a Topic")
                                .font(AppTypography.displayMedium)
                                .foregroundColor(BrandColors.textPrimary)
                            
                            Text("Select a topic to see curated news")
                                .font(AppTypography.bodyMedium)
                                .foregroundColor(BrandColors.textSecondary)
                                .multilineTextAlignment(.center)
                        }
                        
                        VStack(spacing: AppSpacing.md) {
                            ForEach(NewsTopic.allCases, id: \.self) { topic in
                                Button(action: {
                                    withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                                        viewModel.selectTopic(topic)
                                    }
                                    Task {
                                        await viewModel.curateNews()
                                    }
                                }) {
                                    HStack(spacing: AppSpacing.md) {
                                        ZStack {
                                            Circle()
                                                .fill(AppGradients.primary.opacity(0.15))
                                                .frame(width: 44, height: 44)
                                            
                                            Image(systemName: topic.iconName)
                                                .font(.system(size: 20, weight: .semibold))
                                                .foregroundColor(BrandColors.primary)
                                        }
                                        
                                        VStack(alignment: .leading, spacing: AppSpacing.xs) {
                                            Text(topic.displayName)
                                                .font(AppTypography.headlineMedium)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text(topic.description)
                                                .font(AppTypography.bodySmall)
                                                .foregroundColor(BrandColors.textSecondary)
                                        }
                                        
                                        Spacer()
                                        
                                        Image(systemName: "chevron.right")
                                            .font(.system(size: 14, weight: .semibold))
                                            .foregroundColor(BrandColors.textSecondary)
                                    }
                                    .padding(AppSpacing.md)
                                    .background(BrandColors.secondaryBackground)
                                    .cornerRadius(AppCornerRadius.medium)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                                            .stroke(BrandColors.primary.opacity(0.1), lineWidth: 1)
                                    )
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal, AppSpacing.lg)
                        .padding(.top, AppSpacing.xl)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(BrandColors.background)
                }
                // Show empty state only if topic is selected but no articles
                else if viewModel.curatedArticles.isEmpty && !viewModel.isCurating {
                    // Empty state
                    VStack(spacing: AppSpacing.lg) {
                        ZStack {
                            Circle()
                                .fill(BrandColors.primary.opacity(0.1))
                                .frame(width: 100, height: 100)
                            
                            Image(systemName: "newspaper")
                                .font(.system(size: 45, weight: .medium))
                                .foregroundColor(BrandColors.primary)
                        }
                        
                        VStack(spacing: AppSpacing.sm) {
                            Text("No articles available")
                                .font(AppTypography.headlineLarge)
                                .foregroundColor(BrandColors.textPrimary)
                            
                            if let error = viewModel.errorMessage {
                                Text(error)
                                    .font(AppTypography.bodySmall)
                                    .foregroundColor(BrandColors.error)
                                    .multilineTextAlignment(.center)
                                    .padding(.horizontal, AppSpacing.lg)
                            } else {
                                Text("Try refreshing to get the latest news")
                                    .font(AppTypography.bodyMedium)
                                    .foregroundColor(BrandColors.textSecondary)
                                    .multilineTextAlignment(.center)
                            }
                        }
                        
                        Button(action: {
                            Task {
                                await viewModel.curateNews()
                            }
                        }) {
                            HStack(spacing: AppSpacing.sm) {
                                Image(systemName: "arrow.clockwise")
                                    .font(.system(size: 16, weight: .semibold))
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
                            
                            // Curated Articles Section
                            if !viewModel.curatedArticles.isEmpty, let topic = viewModel.selectedTopic {
                                VStack(alignment: .leading, spacing: AppSpacing.md) {
                                    HStack {
                                        VStack(alignment: .leading, spacing: AppSpacing.xs) {
                                            HStack(spacing: AppSpacing.sm) {
                                                ZStack {
                                                    Circle()
                                                        .fill(AppGradients.primary.opacity(0.2))
                                                        .frame(width: 32, height: 32)
                                                    
                                                    Image(systemName: "sparkles")
                                                        .font(.system(size: 16, weight: .semibold))
                                                        .foregroundColor(BrandColors.primary)
                                                }
                                                
                                                Text("\(topic.displayName) News")
                                                    .font(AppTypography.displaySmall)
                                                    .foregroundColor(BrandColors.textPrimary)
                                            }
                                            Text("\(viewModel.curatedArticles.count) carefully selected articles")
                                                .font(AppTypography.bodySmall)
                                                .foregroundColor(BrandColors.textSecondary)
                                        }
                                        Spacer()
                                        
                                        // Topic selector button
                                        Menu {
                                            ForEach(NewsTopic.allCases, id: \.self) { otherTopic in
                                                Button(action: {
                                                    withAnimation {
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
                                            Image(systemName: "ellipsis.circle.fill")
                                                .font(.system(size: 20))
                                                .foregroundColor(BrandColors.primary)
                                        }
                                    }
                                    .padding(.horizontal, AppSpacing.md)
                                    .padding(.top, AppSpacing.md)
                                    
                                    ForEach(viewModel.curatedArticles) { article in
                                        ArticleCardView(article: article)
                                            .padding(.horizontal, AppSpacing.md)
                                            .padding(.bottom, AppSpacing.md)
                                    }
                                }
                                .padding(.bottom, AppSpacing.md)
                            }
                            
                            // Hide regular articles section - we only show headlines and curated articles
                        }
                    }
                    .refreshable {
                        await viewModel.curateNews()
                    }
                }
                
                // Curating loading overlay
                if viewModel.isCurating {
                    ZStack {
                        Color.black.opacity(0.5)
                            .ignoresSafeArea()
                        
                        VStack(spacing: AppSpacing.lg) {
                            ZStack {
                                Circle()
                                    .fill(AppGradients.primary.opacity(0.2))
                                    .frame(width: 80, height: 80)
                                
                                ProgressView()
                                    .scaleEffect(1.5)
                                    .tint(BrandColors.primary)
                                    .progressViewStyle(CircularProgressViewStyle())
                            }
                            
                            VStack(spacing: AppSpacing.sm) {
                                Text("Getting Fresh News")
                                    .foregroundColor(BrandColors.textPrimary)
                                    .font(AppTypography.headlineLarge)
                                
                                if let topic = viewModel.selectedTopic {
                                    Text("Finding \(topic.displayName) news articles...")
                                        .foregroundColor(BrandColors.textSecondary)
                                        .font(AppTypography.bodyMedium)
                                        .multilineTextAlignment(.center)
                                } else {
                                    Text("Finding news articles...")
                                        .foregroundColor(BrandColors.textSecondary)
                                        .font(AppTypography.bodyMedium)
                                        .multilineTextAlignment(.center)
                                }
                            }
                        }
                        .padding(AppSpacing.xl)
                        .background(BrandColors.cardBackground)
                        .cornerRadius(AppCornerRadius.xlarge)
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
                        Task {
                            await viewModel.curateNews()
                        }
                    }) {
                        HStack(spacing: AppSpacing.xs) {
                            if viewModel.isCurating {
                                ProgressView()
                                    .progressViewStyle(CircularProgressViewStyle(tint: BrandColors.primary))
                                    .scaleEffect(0.8)
                            } else {
                                Image(systemName: "sparkles")
                                    .font(.system(size: 14, weight: .semibold))
                            }
                            Text("Get Fresh News")
                                .font(AppTypography.labelMedium)
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
                                        .font(.title2)
                                }
                            }
                            .frame(width: 32, height: 32)
                            .clipShape(Circle())
                        } else {
                            Image(systemName: "person.circle.fill")
                                .font(.title2)
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

