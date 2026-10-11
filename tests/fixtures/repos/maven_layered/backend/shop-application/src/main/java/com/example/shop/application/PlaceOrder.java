package com.example.shop.application;

import com.example.shop.domain.Order;

public class PlaceOrder {
    public Order place(String id) { return new Order(id, 1); }
}
