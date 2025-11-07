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
                    VStack(spacing: 24) {
                        Image(systemName: "newspaper.fill")
                            .font(.system(size: 70))
                            .foregroundColor(.blue)
                        
                        Text("Choose a Topic")
                            .font(.title)
                            .fontWeight(.bold)
                        
                        Text("Select a topic to see curated news")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                        
                        VStack(spacing: 16) {
                            ForEach(NewsTopic.allCases, id: \.self) { topic in
                                Button(action: {
                                    viewModel.selectTopic(topic)
                                    Task {
                                        await viewModel.curateNews()
                                    }
                                }) {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(topic.displayName)
                                                .font(.headline)
                                                .foregroundColor(.primary)
                                            Text(topic.description)
                                                .font(.caption)
                                                .foregroundColor(.secondary)
                                        }
                                        Spacer()
                                        Image(systemName: "chevron.right")
                                            .foregroundColor(.secondary)
                                    }
                                    .padding()
                                    .background(Color(.systemGray6))
                                    .cornerRadius(12)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal, 24)
                        .padding(.top, 32)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                // Show empty state only if topic is selected but no articles
                else if viewModel.curatedArticles.isEmpty && !viewModel.isCurating {
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
                        Button("Get Fresh News") {
                            Task {
                                await viewModel.curateNews()
                            }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                } else if viewModel.selectedTopic != nil {
                    ScrollView {
                        VStack(spacing: 0) {
                            // Error banner
                            if let error = viewModel.errorMessage, !error.isEmpty {
                                HStack {
                                    Image(systemName: "exclamationmark.triangle.fill")
                                        .foregroundColor(.orange)
                                    Text(error)
                                        .font(.subheadline)
                                        .foregroundColor(.primary)
                                    Spacer()
                                    Button("Dismiss") {
                                        viewModel.errorMessage = nil
                                    }
                                    .font(.caption)
                                }
                                .padding()
                                .background(Color.orange.opacity(0.1))
                                .cornerRadius(8)
                                .padding(.horizontal, 16)
                                .padding(.top, 8)
                            }
                            
                            // Curated Articles Section
                            if !viewModel.curatedArticles.isEmpty, let topic = viewModel.selectedTopic {
                                VStack(alignment: .leading, spacing: 12) {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 4) {
                                            HStack(spacing: 6) {
                                                Image(systemName: "sparkles")
                                                    .foregroundColor(.blue)
                                                Text("\(topic.displayName) News")
                                                    .font(.title2)
                                                    .fontWeight(.bold)
                                            }
                                            Text("\(viewModel.curatedArticles.count) carefully selected articles")
                                                .font(.caption)
                                                .foregroundColor(.secondary)
                                        }
                                        Spacer()
                                        
                                        // Topic selector button
                                        Menu {
                                            ForEach(NewsTopic.allCases, id: \.self) { otherTopic in
                                                Button(action: {
                                                    viewModel.selectTopic(otherTopic)
                                                    Task {
                                                        await viewModel.curateNews()
                                                    }
                                                }) {
                                                    HStack {
                                                        Text(otherTopic.displayName)
                                                        if otherTopic == topic {
                                                            Image(systemName: "checkmark")
                                                        }
                                                    }
                                                }
                                            }
                                        } label: {
                                            Image(systemName: "ellipsis.circle")
                                                .foregroundColor(.blue)
                                        }
                                    }
                                    .padding(.horizontal, 16)
                                    .padding(.top, 16)
                                    
                                    ForEach(viewModel.curatedArticles) { article in
                                        ArticleCardView(article: article)
                                            .padding(.horizontal, 16)
                                            .padding(.bottom, 12)
                                    }
                                }
                                .padding(.bottom, 16)
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
                        Color.black.opacity(0.4)
                            .ignoresSafeArea()
                        VStack(spacing: 20) {
                            ProgressView()
                                .scaleEffect(1.5)
                                .tint(.blue)
                            VStack(spacing: 8) {
                                Text("Getting Fresh News")
                                    .foregroundColor(.primary)
                                    .font(.headline)
                                    .fontWeight(.semibold)
                                if let topic = viewModel.selectedTopic {
                                    Text("Finding \(topic.displayName) news articles...")
                                        .foregroundColor(.secondary)
                                        .font(.subheadline)
                                        .multilineTextAlignment(.center)
                                        .padding(.horizontal)
                                } else {
                                    Text("Finding news articles...")
                                        .foregroundColor(.secondary)
                                        .font(.subheadline)
                                        .multilineTextAlignment(.center)
                                        .padding(.horizontal)
                                }
                            }
                        }
                        .padding(32)
                        .background(Color(.systemBackground))
                        .cornerRadius(20)
                        .shadow(color: Color.black.opacity(0.2), radius: 20, x: 0, y: 10)
                        .padding(.horizontal, 40)
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
                        HStack(spacing: 4) {
                            if viewModel.isCurating {
                                ProgressView()
                                    .progressViewStyle(CircularProgressViewStyle())
                                    .scaleEffect(0.8)
                            } else {
                                Image(systemName: "sparkles")
                            }
                            Text("Get Fresh News")
                                .font(.subheadline)
                        }
                        .foregroundColor(.blue)
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

