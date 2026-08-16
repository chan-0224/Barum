package com.barum.crud;

import com.barum.common.ApiException;
import com.barum.common.ErrorCode;
import com.barum.config.SecurityConfig;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ProductService {

    private final VanityProductRepository productRepository;
    private final CatalogProductRepository catalogRepository;

    // 3. 내 화장대 목록
    @Transactional
    public ProductDto.ListResponse getMyProducts() {
        UUID userId = UUID.fromString(SecurityConfig.currentUserId());
        List<VanityProduct> products = productRepository.findByUserIdOrderByCreatedAtDesc(userId);

        if (products.isEmpty()) {
            int injected = productRepository.injectSampleVanity(userId);
            if (injected > 0) {
                products = productRepository.findByUserIdOrderByCreatedAtDesc(userId);
            }
        }

        boolean isSample = !products.isEmpty() &&
                products.stream().allMatch(p -> p.getSource() == ProductSource.SAMPLE);

        List<Long> catalogIds = products.stream()
                .map(VanityProduct::getCatalogId)
                .filter(id -> id != null)
                .toList();

        Map<Long, CatalogProduct> catalogMap = catalogRepository.findAllById(catalogIds).stream()
                .collect(Collectors.toMap(CatalogProduct::getId, c -> c));

        List<ProductDto.VanityItem> items = products.stream().map(vp -> {
            CatalogProduct cp = catalogMap.get(vp.getCatalogId());

            if (cp == null) {
                return new ProductDto.VanityItem(
                        vp.getId(), "알수없음", "제품명 없음", "ETC", null,
                        vp.getSource().name(), List.of(), vp.getCreatedAt()
                );
            }

            List<String> keyIngredients = catalogRepository.findKeyIngredientsByCatalogId(vp.getCatalogId());

            return new ProductDto.VanityItem(
                    vp.getId(),
                    cp.getBrand(),
                    cp.getName(),
                    cp.getCategory(),
                    cp.getImageUrl(),
                    vp.getSource().name(),
                    keyIngredients,
                    vp.getCreatedAt()
            );
        }).toList();

        return new ProductDto.ListResponse(isSample, items);
    }

    @Transactional
    public void initSampleVanity() {
        UUID userId = UUID.fromString(SecurityConfig.currentUserId());
        productRepository.injectSampleVanity(userId);
    }

    // 4. 제품 등록
    @Transactional
    public ProductDto.CreateResponse addProducts(ProductDto.CreateRequest request) {
        UUID userId = UUID.fromString(SecurityConfig.currentUserId());
        List<VanityProduct> existingProducts = productRepository.findByUserId(userId);

        boolean isSample = !existingProducts.isEmpty() &&
                existingProducts.stream().allMatch(p -> p.getSource() == ProductSource.SAMPLE);

        boolean sampleCleared = false;
        if (isSample) {
            productRepository.deleteByUserIdAndSource(userId, ProductSource.SAMPLE);
            sampleCleared = true;
        }

        List<VanityProduct> newProducts = new ArrayList<>();

        if (request.catalogIds() != null && !request.catalogIds().isEmpty()) {
            Map<Long, CatalogProduct> catalogs = catalogRepository.findAllById(request.catalogIds()).stream()
                    .collect(Collectors.toMap(CatalogProduct::getId, c -> c));

            for (Long catalogId : request.catalogIds()) {
                CatalogProduct cp = catalogs.get(catalogId);
                if (cp != null) {
                    newProducts.add(new VanityProduct(userId, catalogId, cp.getName(), ProductSource.CATALOG));
                }
            }
        }

        productRepository.saveAll(newProducts);

        List<ProductDto.CreatedItem> createdItems = newProducts.stream()
                .map(vp -> new ProductDto.CreatedItem(vp.getId(), vp.getName()))
                .toList();

        return new ProductDto.CreateResponse(newProducts.size(), sampleCleared, createdItems);
    }

    // 7. 제품 삭제
    @Transactional
    public void deleteProduct(UUID productId) {
        UUID userId = UUID.fromString(SecurityConfig.currentUserId());

        VanityProduct product = productRepository.findByIdAndUserId(productId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.PRODUCT_NOT_FOUND));

        productRepository.delete(product);
    }
}