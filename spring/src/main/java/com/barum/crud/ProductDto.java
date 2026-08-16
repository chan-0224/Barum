package com.barum.crud;

import com.fasterxml.jackson.annotation.JsonFormat;
import java.time.ZonedDateTime;
import java.util.List;
import java.util.UUID;

public class ProductDto {

    public record CreateRequest(
            List<Long> catalogIds
    ) {}

    public record CreateResponse(
            int added,
            boolean sampleCleared,
            List<CreatedItem> items
    ) {}

    public record CreatedItem(UUID productId, String name) {}

    public record ListResponse(
            boolean isSample,
            List<VanityItem> items
    ) {}

    public record VanityItem(
            UUID productId,
            String brand,
            String name,
            String category,
            String imageUrl,
            String source,
            List<String> keyIngredients,
            @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd'T'HH:mm:ssXXX", timezone = "Asia/Seoul")
            ZonedDateTime createdAt
    ) {}
}