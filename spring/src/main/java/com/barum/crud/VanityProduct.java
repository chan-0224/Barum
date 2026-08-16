package com.barum.crud;

import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.ZonedDateTime;
import java.time.ZoneId;
import java.util.UUID;

@Entity
@Table(name = "products") // 명세서 기준 테이블명
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class VanityProduct {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "user_id", nullable = false)
    private UUID userId;

    @Column(name = "catalog_id")
    private Long catalogId;

    @Column(nullable = false)
    private String name;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ProductSource source;

    @Column(name = "created_at", updatable = false)
    private ZonedDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        this.createdAt = ZonedDateTime.now(ZoneId.of("Asia/Seoul"));
    }

    public VanityProduct(UUID userId, Long catalogId, String name, ProductSource source) {
        this.userId = userId;
        this.catalogId = catalogId;
        this.name = name;
        this.source = source;
    }
}