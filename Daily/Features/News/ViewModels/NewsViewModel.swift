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
    @Published var curatedArticles: [NewsArticle] = []
    @Published var isLoading: Bool = false
    @Published var isLoadingHeadlines: Bool = false
    @Published var isCurating: Bool = false
    @Published var isLoadingMore: Bool = false
    @Published var errorMessage: String?
    @Published var hasMore: Bool = true
    @Published var hasLoadedInitialHeadlines: Bool = false
    
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
            self.hasLoadedInitialHeadlines = true
            self.isLoadingHeadlines = false
        } catch {
            // Don't clear headlines on error - keep them if they were loaded before
            self.errorMessage = error.localizedDescription
            self.isLoadingHeadlines = false
            // Don't clear headlines array - keep existing ones
        }
    }
    
    func loadInitialContent() async {
        // For now we only show curated personalized news on demand.
        // Headlines are optional and can be loaded separately if needed.
        return
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
    
    func curateNews() async {
        guard !isCurating else { return }
        
        isCurating = true
        errorMessage = nil
        
        guard let token = authService.getAccessToken() else {
            self.errorMessage = "Authentication required"
            self.isCurating = false
            return
        }
        
        do {
            // Fetch curated articles (AI-analyzed) using the saved per-user profile.
            print("Starting to fetch curated news (personalized if available)...")
            let curated = try await backendService.curateNews(
                accessToken: token,
                topic: "",
                limit: 10
            )
            print("Successfully received \(curated.count) curated articles")
            
            // Ensure we have at least some articles
            if curated.count < 5 && curated.count > 0 {
                print("Warning: Received only \(curated.count) articles (expected at least 5)")
                self.errorMessage = "Only found \(curated.count) articles. Please try again for more results."
            } else if curated.isEmpty {
                self.errorMessage = "No personalized articles found. The AI couldn't find relevant articles from the current news. Please try again later."
            }
            
            self.curatedArticles = curated
            self.isCurating = false
            // Don't clear error message if we have articles but less than 5
            if curated.count >= 5 {
                self.errorMessage = nil
            }
        } catch {
            print("Error curating news: \(error)")
            if let nsError = error as NSError? {
                print("Error domain: \(nsError.domain), code: \(nsError.code)")
                print("Error userInfo: \(nsError.userInfo)")
            }
            self.errorMessage = error.localizedDescription
            self.isCurating = false
        }
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

