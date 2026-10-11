package com.example.shop.api;

import com.example.shop.application.PlaceOrder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {
    private final PlaceOrder placeOrder = new PlaceOrder();

    @PostMapping("/orders")
    public String place() { return placeOrder.place("1").id(); }
}
