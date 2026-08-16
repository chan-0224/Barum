package com.barum.crud;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface VanityProductRepository extends JpaRepository<VanityProduct, UUID> {
    List<VanityProduct> findByUserIdOrderByCreatedAtDesc(UUID userId);

    List<VanityProduct> findByUserId(UUID userId);

    Optional<VanityProduct> findByIdAndUserId(UUID id, UUID userId);

    @Modifying
    @Query("DELETE FROM VanityProduct p WHERE p.userId = :userId AND p.source = :source")
    void deleteByUserIdAndSource(@Param("userId") UUID userId, @Param("source") ProductSource source);

    /**
     * 익명 세션 최초 진입 시 샘플 화장대(13종) 세팅
     * 이미 제품이 1개라도 있으면 작동하지 않음 (WHERE NOT EXISTS 조건)
     */
    @Modifying
    @Query(value = """
        INSERT INTO products (user_id, catalog_id, name, source)
        SELECT :userId, catalog_id, name, 'SAMPLE'
          FROM sample_vanity
         WHERE NOT EXISTS (SELECT 1 FROM products WHERE user_id = :userId)
        """, nativeQuery = true)
    int injectSampleVanity(@Param("userId") UUID userId);
}