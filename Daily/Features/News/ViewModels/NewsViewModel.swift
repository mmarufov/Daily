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
    @Published var isPreparingArticles: Bool = false
    @Published var preparationStatus: String?
    
    // Background-aware curated news state
    @Published var lastCuratedFetchDate: Date?
    
    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    private let backgroundFetcher = BackgroundNewsFetcher.shared
    
    private var currentOffset: Int = 0
    private let pageSize: Int = 20
    
    // MARK: - Init
    
    init() {
        // Load any previously saved curated articles for this user from the backend/Neon DB.
        Task {
            await loadSavedCuratedNews()
        }
        
        NotificationCenter.default.addObserver(
            forName: .curatedNewsReady,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                await self?.handleCuratedNewsReady()
            }
        }
    }
    
    deinit {
        NotificationCenter.default.removeObserver(self)
    }
    
    // MARK: - Private Helpers
    
    @MainActor
    private func handleCuratedNewsReady() async {
        let articles = backgroundFetcher.lastCuratedArticles.map { $0.normalizedForDisplay() }
        curatedArticles = articles
        isCurating = false
        errorMessage = backgroundFetcher.lastErrorMessage
        lastCuratedFetchDate = UserDefaults.standard.object(forKey: "BackgroundNewsFetcher.lastFetchDate") as? Date
        
        // Ensure images are preloaded when articles come from background fetch
        ImageCacheService.shared.preloadImages(for: articles)
    }
    
    // MARK: - Public Methods
    
    /// Load the last curated news set for the current user from the backend database.
    /// This does NOT trigger a fresh fetch; it only reads what was saved previously.
    func loadSavedCuratedNews() async {
        guard !isCurating else { return }
        
        errorMessage = nil
        
        guard let token = authService.getAccessToken() else {
            // Don't set error message if not authenticated - user might not be logged in yet
            return
        }
        
        do {
            let articles = try await backendService.fetchCuratedNews(accessToken: token).map { $0.normalizedForDisplay() }
            await MainActor.run {
                self.curatedArticles = articles
                if !articles.isEmpty {
                    ImageCacheService.shared.preloadImages(for: articles)
                } else {
                    // Empty list is valid - user hasn't fetched news yet or no articles were saved
                    print("No saved curated articles found in database")
                }
            }
        } catch {
            // Only show error if it's not a "not found" or empty response
            let errorMsg = error.localizedDescription.lowercased()
            if errorMsg.contains("not found") || errorMsg.contains("404") {
                // Empty state is fine - user just hasn't fetched news yet
                await MainActor.run {
                    self.curatedArticles = []
                    self.errorMessage = nil
                }
            } else {
                await MainActor.run {
                    self.errorMessage = error.localizedDescription
                }
            }
        }
    }
    
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
        
        guard let token = authService.getAccessToken() else {
            self.errorMessage = "Authentication required"
            return
        }
        
        isCurating = true
        errorMessage = nil
        
        // Start a background-capable curated fetch. This call returns immediately;
        // the result will be delivered via NotificationCenter / published state.
        backgroundFetcher.startCuratedNewsFetch(accessToken: token, topic: "", limit: 10)
    }
    
    /// Prepare all curated articles by extracting and caching their full content.
    /// This will make articles open instantly when users tap on them.
    func prepareAllArticles() async {
        guard !isPreparingArticles else { return }
        guard !curatedArticles.isEmpty else {
            self.errorMessage = "No articles to prepare"
            return
        }
        
        guard let token = authService.getAccessToken() else {
            self.errorMessage = "Authentication required"
            return
        }
        
        isPreparingArticles = true
        preparationStatus = "Starting preparation..."
        errorMessage = nil
        
        do {
            let response = try await backendService.prepareArticles(accessToken: token)
            
            await MainActor.run {
                self.isPreparingArticles = false
                self.preparationStatus = response.message
                
                // Reload articles to get updated content
                Task {
                    await self.loadSavedCuratedNews()
                }
                
                // Show success message briefly
                if response.processed > 0 {
                    self.errorMessage = nil
                    // Clear status after a delay
                    Task {
                        try? await Task.sleep(nanoseconds: 3_000_000_000) // 3 seconds
                        await MainActor.run {
                            self.preparationStatus = nil
                        }
                    }
                } else if response.failed > 0 {
                    self.errorMessage = "Some articles failed to prepare. Please try again."
                }
            }
        } catch {
            await MainActor.run {
                self.isPreparingArticles = false
                self.preparationStatus = nil
                self.errorMessage = "Failed to prepare articles: \(error.localizedDescription)"
            }
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

