package com.example.house.network

data class RentalLocationRequest(
    val work_address1: String,
    val work_address2: String,
    val budget_range: String,
    val preferences: String
)

data class RentalLocationResponse(
    val rental_location_analysis: String
)
