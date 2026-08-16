package com.barum.crud;

import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import java.time.ZonedDateTime;

@Entity
@Table(name = "catalog_products")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class CatalogProduct {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String brand;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private String category;

    @Column(name = "image_url")
    private String imageUrl;

    @Column(name = "raw_ingredients", columnDefinition = "TEXT")
    private String rawIngredients;

    @Column(name = "created_at", updatable = false)
    private ZonedDateTime createdAt;
}