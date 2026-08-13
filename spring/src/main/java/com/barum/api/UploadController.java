package com.barum.api;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.barum.client.StorageClient;
import com.barum.common.ApiException;
import com.barum.common.ErrorCode;
import com.barum.config.SecurityConfig;

/** API.md 5 — 업로드 URL 발급 (화면 2·9). */
@RestController
@RequestMapping("/api/v1/uploads")
public class UploadController {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final int EXPIRES_IN = 300;

    private final StorageClient storage;

    public UploadController(StorageClient storage) {
        this.storage = storage;
    }

    public record UploadRequest(String purpose) {}

    @PostMapping
    public Map<String, Object> create(@RequestBody UploadRequest req) {
        String userId = SecurityConfig.currentUserId();
        String purpose = req.purpose() == null ? "" : req.purpose().toUpperCase();

        String bucket;
        String path;
        switch (purpose) {
            case "OCR" -> {
                bucket = StorageClient.BUCKET_LABEL;
                path = userId + "/" + UUID.randomUUID() + ".jpg";
            }
            case "SELFIE" -> {
                bucket = StorageClient.BUCKET_SELFIE;
                // 하루 한 장. 다시 찍으면 같은 경로를 덮어쓴다(daily_records도 날짜당 1행)
                path = userId + "/" + LocalDate.now(KST) + ".jpg";
            }
            default -> throw new ApiException(ErrorCode.VALIDATION_ERROR, "purpose는 OCR 또는 SELFIE여야 합니다.");
        }

        // 경로 첫 폴더가 userId여야 Storage 정책을 통과한다. 위에서 항상 userId로 시작하게 만든다
        String url = storage.signedUploadUrl(SecurityConfig.currentJwt(), bucket, path);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("uploadUrl", url);
        out.put("bucket", bucket);
        out.put("storagePath", path);
        out.put("expiresIn", EXPIRES_IN);
        return out;
    }
}
