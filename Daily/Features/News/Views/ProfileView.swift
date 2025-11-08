//
//  ProfileView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

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
                    // Profile Header
                    VStack(spacing: AppSpacing.lg) {
                        // Profile Image
                        ZStack {
                            Circle()
                                .fill(AppGradients.primary.opacity(0.2))
                                .frame(width: 140, height: 140)
                            
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
                                            .font(.system(size: 80, weight: .light))
                                            .foregroundColor(BrandColors.primary)
                                    }
                                }
                                .frame(width: 120, height: 120)
                                .clipShape(Circle())
                                .overlay(
                                    Circle()
                                        .stroke(BrandColors.primary, lineWidth: 4)
                                )
                            } else {
                                Image(systemName: "person.circle.fill")
                                    .font(.system(size: 80, weight: .light))
                                    .foregroundColor(BrandColors.primary)
                                    .frame(width: 120, height: 120)
                            }
                        }
                        .padding(.top, AppSpacing.xxl)
                        
                        // User Info
                        VStack(spacing: AppSpacing.sm) {
                            if let displayName = auth.currentUser?.display_name {
                                Text(displayName)
                                    .font(AppTypography.displaySmall)
                                    .foregroundColor(BrandColors.textPrimary)
                            }
                            
                            if let email = auth.currentUser?.email {
                                Text(email)
                                    .font(AppTypography.bodyMedium)
                                    .foregroundColor(BrandColors.textSecondary)
                            }
                        }
                    }
                    
                    Spacer()
                    
                    // Sign Out Button
                    Button(action: {
                        auth.signOut()
                        dismiss()
                    }) {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "arrow.right.square")
                                .font(.system(size: 16, weight: .semibold))
                            Text("Sign Out")
                                .font(AppTypography.labelLarge)
                        }
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 56)
                        .background(
                            LinearGradient(
                                colors: [BrandColors.error, BrandColors.error.opacity(0.8)],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .cornerRadius(AppCornerRadius.medium)
                        .shadow(
                            color: BrandColors.error.opacity(0.3),
                            radius: 8,
                            x: 0,
                            y: 4
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
                    .font(AppTypography.labelLarge)
                    .foregroundColor(BrandColors.primary)
                }
            }
        }
    }
}

#Preview {
    ProfileView()
}

