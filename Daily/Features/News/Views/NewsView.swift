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
                // Show empty state only if both headlines and articles are empty
                if viewModel.headlines.isEmpty && viewModel.articles.isEmpty && !viewModel.isLoading && !viewModel.isLoadingHeadlines {
                    // Empty state
                    VStack(spacing: 16) {
                        Image(systemName: "newspaper")
                            .font(.system(size: 60))
                            .foregroundColor(.secondary)
                        Text("No articles available")
                            .font(.headline)
                            .foregroundColor(.secondary)
                        if let error = viewModel.errorMessage {
                            Text(error)
                                .font(.caption)
                                .foregroundColor(.red)
                                .multilineTextAlignment(.center)
                                .padding(.horizontal)
                        }
                        Button("Retry") {
                            Task {
                                await viewModel.loadHeadlines()
                                // Don't refresh articles for now - that endpoint doesn't exist yet
                                // await viewModel.refreshArticles()
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                } else {
                    ScrollView {
                        VStack(spacing: 0) {
                            // Headlines Section
                            if !viewModel.headlines.isEmpty {
                                VStack(alignment: .leading, spacing: 12) {
                                    HStack {
                                        Text("Top Headlines")
                                            .font(.title2)
                                            .fontWeight(.bold)
                                            .padding(.horizontal, 16)
                                        Spacer()
                                    }
                                    .padding(.top, 8)
                                    
                                    ScrollView(.horizontal, showsIndicators: false) {
                                        HStack(spacing: 16) {
                                            ForEach(viewModel.headlines) { headline in
                                                HeadlineCardView(article: headline)
                                                    .frame(width: 300)
                                            }
                                        }
                                        .padding(.horizontal, 16)
                                    }
                                }
                                .padding(.vertical, 16)
                                .background(Color(.systemGroupedBackground))
                                
                                // Divider
                                Divider()
                            }
                            
                            // Regular Articles Section
                            LazyVStack(spacing: 20) {
                                if !viewModel.headlines.isEmpty {
                                    HStack {
                                        Text("More News")
                                            .font(.title2)
                                            .fontWeight(.bold)
                                        Spacer()
                                    }
                                    .padding(.horizontal, 16)
                                    .padding(.top, 16)
                                }
                                
                                ForEach(viewModel.articles) { article in
                                    ArticleCardView(article: article)
                                        .padding(.horizontal, 16)
                                        .onAppear {
                                            // Load more when reaching near the end
                                            if article.id == viewModel.articles.suffix(3).first?.id {
                                                Task {
                                                    await viewModel.loadMoreArticles()
                                                }
                                            }
                                        }
                                }
                                
                                // Loading indicator at bottom
                                if viewModel.isLoadingMore {
                                    ProgressView()
                                        .padding()
                                }
                            }
                            .padding(.vertical, 8)
                        }
                    }
                    .refreshable {
                        await viewModel.loadHeadlines()
                        // Don't refresh articles for now - that endpoint doesn't exist yet
                        // await viewModel.refreshArticles()
                    }
                }
                
                // Full screen loading
                if viewModel.isLoading && viewModel.articles.isEmpty {
                    ProgressView()
                }
            }
            .navigationTitle("Daily")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
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
            .task {
                await viewModel.loadHeadlines()
                // Don't load articles for now - that endpoint doesn't exist yet
                // await viewModel.loadArticles()
            }
        }
    }
}

#Preview {
    NewsView()
}

