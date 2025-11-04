//
//  User.swift
//  Daily
//
//  Created by Assistant on 11/4/25.
//

import Foundation

struct User: Codable, Identifiable, Equatable {
    let id: UUID
    let email: String?
    let display_name: String?
    let photo_url: String?
}


