package com.barum.client;

import java.time.Duration;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import com.barum.common.ApiException;
import com.barum.common.ErrorCode;

/**
 * FastAPI AI 서버 호출.
 *
 * <p>날씨를 Java로 다시 구현하지 않고 여기로 넘기는 이유: 격자좌표 변환·시도 판정·캐싱이
 * 이미 {@code barum-be/daily_context.py}에 있고 실측 검증까지 끝났다. Java로 옮기면
 * 같은 로직이 두 벌이 되고 캐시도 따로 돈다. CLAUDE.md도 이 함수 하나를 소스 교체
 * 지점으로 못박아 뒀다.
 */
@Component
public class AiClient {

    private static final Logger log = LoggerFactory.getLogger(AiClient.class);

    private final RestClient http;
    private final String internalKey;

    public AiClient(@Value("${barum.ai.base-url}") String baseUrl,
                    @Value("${barum.ai.internal-key}") String internalKey) {
        this.internalKey = internalKey;
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(Duration.ofSeconds(3));
        // 에어코리아가 20초를 넘긴 적이 있다(docs/DATA.md). 날씨는 넉넉히 준다
        f.setReadTimeout(Duration.ofSeconds(45));
        this.http = RestClient.builder().baseUrl(baseUrl).requestFactory(f).build();
    }

    /** 오늘의 날씨 컨텍스트. 실패하면 502 — 화면은 날씨 영역만 비우고 나머지는 정상 동작한다. */
    @SuppressWarnings("unchecked")
    public Map<String, Object> dailyContext(double lat, double lon) {
        try {
            return http.get()
                    .uri(b -> b.path("/internal/v1/context/daily")
                            .queryParam("lat", lat).queryParam("lon", lon).build())
                    .header("X-Internal-Key", internalKey)
                    .retrieve()
                    .body(Map.class);
        } catch (Exception e) {
            log.warn("AI 서버 날씨 조회 실패: {}", e.toString());
            throw new ApiException(ErrorCode.EXTERNAL_API_ERROR);
        }
    }

    /** 전성분표 OCR. AI 서버 명세 확정 전까지는 요청을 그대로 넘기는 프록시다. */
    @SuppressWarnings("unchecked")
    public Map<String, Object> ocrIngredients(Map<String, Object> body) {
        try {
            return http.post()
                    .uri("/internal/v1/ocr/ingredients")
                    .header("X-Internal-Key", internalKey)
                    .body(body)
                    .retrieve()
                    .body(Map.class);
        } catch (Exception e) {
            log.warn("AI 서버 OCR 실패: {}", e.toString());
            throw new ApiException(ErrorCode.AI_TIMEOUT);
        }
    }
}
