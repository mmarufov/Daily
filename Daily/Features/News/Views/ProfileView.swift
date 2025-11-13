//
//  ProfileView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI
import UIKit

struct ProfileView: View {
    @ObservedObject private var auth = AuthService.shared
    @Environment(\.dismiss) private var dismiss
    
    var body: some View {
        NavigationView {
            ZStack {
                // Background
                BrandColors.background
                    .ignoresSafeArea()
                
                VStack(spacing: 0) {
                    // Profile Header - Apple style
                    VStack(spacing: AppSpacing.xl) {
                        // Profile Image
                        ZStack {
                            Circle()
                                .fill(BrandColors.primary.opacity(0.1))
                                .frame(width: 120, height: 120)
                            
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
                                            .font(.system(size: 70, weight: .ultraLight))
                                            .foregroundColor(BrandColors.primary)
                                    }
                                }
                                .frame(width: 100, height: 100)
                                .clipShape(Circle())
                                .overlay(
                                    Circle()
                                        .stroke(BrandColors.primary.opacity(0.2), lineWidth: 2)
                                )
                            } else {
                                Image(systemName: "person.circle.fill")
                                    .font(.system(size: 70, weight: .ultraLight))
                                    .foregroundColor(BrandColors.primary)
                                    .frame(width: 100, height: 100)
                            }
                        }
                        .padding(.top, AppSpacing.xxl)
                        
                        // User Info - Apple style
                        VStack(spacing: AppSpacing.xs) {
                            if let displayName = auth.currentUser?.display_name {
                                Text(displayName)
                                    .font(AppTypography.title2)
                                    .foregroundColor(BrandColors.textPrimary)
                            }
                            
                            if let email = auth.currentUser?.email {
                                Text(email)
                                    .font(AppTypography.subheadline)
                                    .foregroundColor(BrandColors.textSecondary)
                            }
                        }
                    }
                    
                    Spacer()
                    
                    // Sign Out Button - Apple style
                    Button(action: {
                        let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                        impactFeedback.impactOccurred()
                        
                        auth.signOut()
                        dismiss()
                    }) {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "arrow.right.square")
                                .font(.system(size: 15, weight: .medium))
                            Text("Sign Out")
                                .font(AppTypography.labelLarge)
                        }
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 50)
                        .background(BrandColors.error)
                        .cornerRadius(AppCornerRadius.button)
                        .shadow(
                            color: BrandColors.error.opacity(0.2),
                            radius: 6,
                            x: 0,
                            y: 3
                        )
                    }
                    .padding(.horizontal, AppSpacing.xl)
                    .padding(.bottom, AppSpacing.xl)
                }
            }
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .font(AppTypography.body)
                    .foregroundColor(BrandColors.primary)
                }
            }
        }
    }
}

#Preview {
    ProfileView()
}

