//
//  SuccessView.swift
//  Daily
//
//  Created by Assistant on 11/4/25.
//

import SwiftUI

struct SuccessView: View {
    @ObservedObject private var auth = AuthService.shared

    var body: some View {
        VStack(spacing: 16) {
            Text("You successfully logged in!")
                .font(.title2)
                .multilineTextAlignment(.center)

            if let user = auth.currentUser {
                Text(user.email ?? "")
                    .foregroundColor(.secondary)
            }

            Button("Sign out") {
                auth.signOut()
            }
            .buttonStyle(.bordered)
        }
        .padding()
    }
}

#Preview {
    SuccessView()
}


