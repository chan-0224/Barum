package com.barum.crud;

import java.util.List;

/** API.md 3·4의 요청·응답 형태. 응답은 LinkedHashMap으로 조립하므로 여기엔 요청만 둔다. */
public class ProductDto {

    /**
     * 4번 요청. 둘 중 하나만 채워 보낸다.
     *
     * @param catalogIds  (a) 카탈로그에서 고른 제품 id
     * @param ocrProduct  (b) 6번 응답을 그대로 전달
     */
    public record CreateRequest(List<Long> catalogIds, OcrProduct ocrProduct) {}

    /** 6번 응답과 같은 형태. 프론트가 들고 있다가 그대로 보낸다. */
    public record OcrProduct(String alias, List<OcrIngredient> ingredients) {}

    /**
     * 매칭 성공이면 standardName, 실패면 rawName이 온다.
     * 실패분도 버리지 않는다 — 화면에 회색으로 보여 주고 나중에 다시 매칭할 수 있어야 한다.
     */
    public record OcrIngredient(String standardName, String rawName, Boolean matched) {

        /** 화면·DB에 남길 원문. 둘 중 있는 쪽을 쓴다. */
        public String display() {
            String s = standardName != null && !standardName.isBlank() ? standardName : rawName;
            return s == null ? null : s.trim();
        }

        /** 표준 성분으로 이어 붙일 이름. matched가 아니면 없다. */
        public String toMatch() {
            if (!Boolean.TRUE.equals(matched)) {
                return null;
            }
            return standardName == null || standardName.isBlank() ? null : standardName.trim();
        }
    }
}
