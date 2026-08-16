package com.barum.crud;

import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/products")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    @PostMapping("/init")
    public ResponseEntity<Void> initSampleVanity() {
        productService.initSampleVanity();
        return ResponseEntity.ok().build();
    }

    // 3. 내 화장대 목록
    @GetMapping
    public ResponseEntity<ProductDto.ListResponse> getProducts() {
        return ResponseEntity.ok(productService.getMyProducts());
    }

    // 4. 제품 등록
    @PostMapping
    public ResponseEntity<ProductDto.CreateResponse> addProducts(
            @RequestBody ProductDto.CreateRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(productService.addProducts(request));
    }

    // 7. 제품 삭제
    @DeleteMapping("/{productId}")
    public ResponseEntity<Void> deleteProduct(@PathVariable UUID productId) {
        productService.deleteProduct(productId);
        return ResponseEntity.noContent().build();
    }
}