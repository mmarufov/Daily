//
//  ContentView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

struct ContentView: View {
    @ObservedObject private var auth = AuthService.shared

    var body: some View {
        ZStack {
            AppleBackgroundView()
            
            Group {
                if auth.isAuthenticated {
                    MainTabView()
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                } else {
                    AuthView()
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .animation(.easeInOut(duration: 0.28), value: auth.isAuthenticated)
        }
    }
}

#Preview {
    ContentView()
}
