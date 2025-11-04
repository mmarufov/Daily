//
//  ContentView.swift
//  Daily
//
//  Created by Muhammad on 3/11/25.
//

import SwiftUI

struct ContentView: View {
    @ObservedObject private var auth = AuthService.shared

    var body: some View {
        Group {
            if auth.isAuthenticated {
                SuccessView()
            } else {
                AuthView()
            }
        }
    }
}

#Preview {
    ContentView()
}
