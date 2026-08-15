package com.barum.api;

import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.barum.client.AiClient;

/** API.md 1 — 날씨 조회 (화면 1). */
@RestController
@RequestMapping("/api/v1/weather")
public class WeatherController {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final double SEOUL_LAT = 37.5665;
    private static final double SEOUL_LON = 126.9780;

    private final AiClient ai;

    public WeatherController(AiClient ai) {
        this.ai = ai;
    }

    @GetMapping
    public Map<String, Object> weather(
            @RequestParam(required = false) Double lat,
            @RequestParam(required = false) Double lon) {

        // 위치 거부 시 서울 폴백 (SCREENS.md 전역 규칙)
        double la = lat != null ? lat : SEOUL_LAT;
        double lo = lon != null ? lon : SEOUL_LON;

        Map<String, Object> ctx = ai.dailyContext(la, lo);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("temp", ctx.get("temp"));
        out.put("humidity", ctx.get("humidity"));
        out.put("pm10", ctx.get("pm10"));
        out.put("pm25", ctx.get("pm25"));
        out.put("regionLabel", ctx.getOrDefault("regionLabel", "서울"));
        out.put("summary", summarize(ctx));
        out.put("observedAt", ZonedDateTime.now(KST).withMinute(0).withSecond(0).withNano(0).toString());
        return out;
    }

    /**
     * 한 줄 요약. 규칙 기반이다 — 날씨 문구까지 LLM에 맡기면 매번 달라지고 비용도 든다.
     * 습도와 미세먼지만 본다. 기온은 숫자로 이미 보이므로 문장에 넣지 않는다.
     */
    static String summarize(Map<String, Object> ctx) {
        Double humidity = asDouble(ctx.get("humidity"));
        Double pm10 = asDouble(ctx.get("pm10"));

        String air;
        if (pm10 == null) {
            air = null;
        } else if (pm10 <= 30) {
            air = "미세먼지는 좋아요";
        } else if (pm10 <= 80) {
            air = "미세먼지는 보통이에요";
        } else if (pm10 <= 150) {
            air = "미세먼지가 나빠요";
        } else {
            air = "미세먼지가 매우 나빠요";
        }

        // 연결형과 종결형을 따로 둔다. "건조해요"에서 요를 고로 바꾸면 "건조해고"가 된다
        String joined = null, ended = null;
        if (humidity != null) {
            if (humidity < 40) {
                joined = "건조하고";
                ended = "건조해요";
            } else if (humidity <= 70) {
                joined = "적당하고";
                ended = "적당해요";
            } else {
                joined = "습하고";
                ended = "습해요";
            }
        }

        if (joined != null && air != null) {
            return joined + " " + air;
        }
        if (air != null) {
            return air;
        }
        return ended != null ? "오늘 공기가 " + ended : "";
    }

    private static Double asDouble(Object v) {
        return v instanceof Number n ? n.doubleValue() : null;
    }
}
