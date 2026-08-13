package com.barum.api;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.barum.client.AiClient;
import com.barum.common.ApiException;
import com.barum.common.ErrorCode;
import com.barum.config.SecurityConfig;

/**
 * API.md 6 — 전성분표 인식 (화면 9·10). AI 서버 몫이라 여기서는 프록시만 한다.
 *
 * <p><b>서버에 저장하지 않는다.</b> 프론트가 응답을 들고 있다가 "저장"을 누르면
 * 제품 등록(API.md 4-b, 왕종휘 담당)으로 보낸다. FastAPI도 DB에 쓰지 않는다(원칙 6).
 *
 * <p>API.md 8(루틴 스트리밍)은 여기 없다. SSE 버퍼링을 피하려고 <b>프론트가 AI 서버를
 * 직접 호출</b>하기로 정해져 있다.
 */
@RestController
@RequestMapping("/api/v1/products")
public class AiProxyController {

    private final AiClient ai;

    public AiProxyController(AiClient ai) {
        this.ai = ai;
    }

    public record OcrRequest(String storagePath, String bucket, String alias) {}

    @PostMapping("/ocr")
    public Map<String, Object> ocr(@RequestBody OcrRequest req) {
        String userId = SecurityConfig.currentUserId();
        if (req.storagePath() == null || req.storagePath().isBlank()) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR, "storagePath가 필요합니다.");
        }
        // 남의 폴더 경로를 넣어 읽게 만드는 걸 막는다. Storage 정책과 같은 규칙을 앞단에서도 건다
        if (!req.storagePath().startsWith(userId + "/")) {
            throw new ApiException(ErrorCode.VALIDATION_ERROR, "잘못된 경로입니다.");
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("storagePath", req.storagePath());
        body.put("bucket", req.bucket() == null ? "labels" : req.bucket());

        Map<String, Object> res = ai.ocrIngredients(body);

        Object count = res.get("matchedCount");
        if (count instanceof Number n && n.intValue() == 0) {
            throw new ApiException(ErrorCode.OCR_NO_TEXT);
        }

        Map<String, Object> out = new LinkedHashMap<>(res);
        out.put("alias", req.alias());
        return out;
    }
}
