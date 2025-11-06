//
//  NewsViewModel.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation
import Combine

@MainActor
final class NewsViewModel: ObservableObject {
    @Published var headlines: [NewsArticle] = []
    @Published var articles: [NewsArticle] = []
    @Published var isLoading: Bool = false
    @Published var isLoadingHeadlines: Bool = false
    @Published var isLoadingMore: Bool = false
    @Published var errorMessage: String?
    @Published var hasMore: Bool = true
    
    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    
    private var currentOffset: Int = 0
    private let pageSize: Int = 20
    
    // MARK: - Public Methods
    
    func loadHeadlines() async {
        guard !isLoadingHeadlines else { return }
        
        isLoadingHeadlines = true
        errorMessage = nil
        
        guard let token = authService.getAccessToken() else {
            self.errorMessage = "Authentication required"
            self.isLoadingHeadlines = false
            return
        }
        
        do {
            let fetchedHeadlines = try await backendService.fetchHeadlines(
                accessToken: token,
                limit: 5
            )
            self.headlines = fetchedHeadlines
            self.isLoadingHeadlines = false
        } catch {
            // Don't clear headlines on error - keep them if they were loaded before
            self.errorMessage = error.localizedDescription
            self.isLoadingHeadlines = false
            // Don't clear headlines array - keep existing ones
        }
    }
    
    func loadArticles() async {
        guard !isLoading else { return }
        
        isLoading = true
        errorMessage = nil
        currentOffset = 0
        
        await fetchArticles(offset: 0, append: false)
    }
    
    func loadArticlesIfAvailable() async {
        // Only try to load articles if the endpoint exists
        // For now, we'll skip this since /articles endpoint doesn't exist yet
        // This prevents errors from clearing the headlines
        return
    }
    
    func loadMoreArticles() async {
        guard !isLoadingMore && hasMore && !isLoading else { return }
        
        isLoadingMore = true
        currentOffset += pageSize
        
        await fetchArticles(offset: currentOffset, append: true)
    }
    
    func refreshArticles() async {
        await loadArticles()
    }
    
    // MARK: - Private Methods
    
    private func fetchArticles(offset: Int, append: Bool) async {
        guard let token = authService.getAccessToken() else {
            self.errorMessage = "Authentication required"
            self.isLoading = false
            self.isLoadingMore = false
            return
        }
        
        do {
            let fetchedArticles = try await backendService.fetchArticles(
                accessToken: token,
                limit: pageSize,
                offset: offset
            )
            
            if append {
                self.articles.append(contentsOf: fetchedArticles)
            } else {
                self.articles = fetchedArticles
            }
            
            self.hasMore = fetchedArticles.count == self.pageSize
            self.isLoading = false
            self.isLoadingMore = false
            self.errorMessage = nil
        } catch {
            self.errorMessage = error.localizedDescription
            self.isLoading = false
            self.isLoadingMore = false
            
            // If this was a refresh, don't clear existing articles
            // Keep existing articles so headlines can still be shown
            if !append {
                // Only clear if we don't have headlines to show
                if self.headlines.isEmpty {
                    self.articles = []
                }
            }
        }
    }
}

