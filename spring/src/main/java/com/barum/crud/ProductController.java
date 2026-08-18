package com.barum.crud;

import java.util.Map;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/** API.md 3·4·7 — 내 화장대 (화면 6 / 8 / 10). */
@RestController
@RequestMapping("/api/v1/products")
public class ProductController {

    private final ProductService products;

    public ProductController(ProductService products) {
        this.products = products;
    }

    /** 3. 목록. 화장대가 비어 있으면 샘플 13종을 넣어 준다. */
    @GetMapping
    public Map<String, Object> list() {
        return products.list();
    }

    /** 4. 등록. catalogIds(카탈로그 선택) 또는 ocrProduct(전성분표) 중 하나. */
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> add(@RequestBody ProductDto.CreateRequest req) {
        return products.add(req);
    }

    /** 7. 삭제. */
    @DeleteMapping("/{productId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable UUID productId) {
        products.delete(productId);
    }
}
