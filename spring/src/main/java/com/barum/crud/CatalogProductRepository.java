package com.barum.crud;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface CatalogProductRepository extends JpaRepository<CatalogProduct, Long> {

    @Query(value = "SELECT std_name FROM catalog_key_ingredients WHERE catalog_id = :catalogId AND rank <= 3 ORDER BY rank", nativeQuery = true)
    List<String> findKeyIngredientsByCatalogId(@Param("catalogId") Long catalogId);
}