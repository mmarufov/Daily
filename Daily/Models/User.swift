//
//  User.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import Foundation

struct User: Codable, Identifiable, Equatable {
    let id: String  // Stack Auth uses string IDs
    let email: String?
    let display_name: String?
    let photo_url: String?
}


