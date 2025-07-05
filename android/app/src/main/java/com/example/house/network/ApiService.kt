package com.example.house.network

import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.POST

interface ApiService {
    @POST("find_rental_location")
    suspend fun findRentalLocation(@Body request: RentalLocationRequest): RentalLocationResponse

    companion object {
        private const val BASE_URL = "http://34.176.0.152:8084/"

        fun create(): ApiService {
            val retrofit = Retrofit.Builder()
                .baseUrl(BASE_URL)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
            return retrofit.create(ApiService::class.java)
        }
    }
}
