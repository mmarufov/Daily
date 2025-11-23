//
//  ImageCacheService.swift
//  Daily
//
//  Created by AI on 11/14/25.
//

import Foundation
import UIKit

/// Service for preloading and caching article images so they're available
/// even when articles are loaded from background fetches.
final class ImageCacheService {
    static let shared = ImageCacheService()
    
    private let urlSession: URLSession
    private let cache: URLCache
    
    private init() {
        // Use a shared cache with reasonable size limits for article images
        // This cache will be used by both our preloading and AsyncImage
        let memoryCapacity = 50 * 1024 * 1024 // 50 MB
        let diskCapacity = 200 * 1024 * 1024 // 200 MB
        cache = URLCache(memoryCapacity: memoryCapacity, diskCapacity: diskCapacity, diskPath: "article_images")
        
        // Configure URLSession.shared to use our cache so AsyncImage can access preloaded images
        // Note: We can't directly modify URLSession.shared, but we can ensure our cache
        // is used by setting it on URLSessionConfiguration.default which AsyncImage may use
        let config = URLSessionConfiguration.default
        config.urlCache = cache
        config.requestCachePolicy = .returnCacheDataElseLoad
        urlSession = URLSession(configuration: config)
        
        // Also set the shared URLCache so AsyncImage's URLSession.shared can use it
        URLCache.shared = cache
    }
    
    /// Preload images for a list of articles. This ensures images are cached
    /// and available when the UI tries to display them.
    func preloadImages(for articles: [NewsArticle]) {
        let imageURLs = articles.compactMap { article -> URL? in
            guard let imageURLString = article.imageURL,
                  let url = URL(string: imageURLString) else {
                return nil
            }
            return url
        }
        
        // Preload images in parallel
        for url in imageURLs {
            preloadImage(url: url)
        }
    }
    
    /// Preload a single image URL into the cache.
    private func preloadImage(url: URL) {
        // Check if already cached
        let request = URLRequest(url: url)
        if let cachedResponse = cache.cachedResponse(for: request) {
            // Already cached, no need to fetch
            return
        }
        
        // Fetch and cache the image
        let task = urlSession.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self,
                  let data = data,
                  let response = response,
                  error == nil else {
                return
            }
            
            // Store in cache
            let cachedResponse = CachedURLResponse(response: response, data: data)
            self.cache.storeCachedResponse(cachedResponse, for: request)
        }
        
        task.resume()
    }
    
    /// Clear the image cache (useful for memory management).
    func clearCache() {
        cache.removeAllCachedResponses()
    }
}

