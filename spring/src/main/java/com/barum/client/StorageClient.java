package com.barum.client;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * Supabase Storage. 얼굴 사진은 민감정보라 비공개 버킷 + Signed URL만 쓴다(원칙 5).
 *
 * <p><b>사용자 JWT를 그대로 실어 보낸다.</b> service_role로 부르면 Storage 정책
 * ({@code (storage.foldername(name))[1] = auth.uid()})이 우회돼 남의 폴더에도 접근할 수 있다.
 * DB와 같은 이유로 여기서도 우회하지 않는다.
 */
@Component
public class StorageClient {

    private static final Logger log = LoggerFactory.getLogger(StorageClient.class);

    /** 용도 구분은 버킷으로 한다. 경로 첫 폴더는 반드시 userId여야 정책을 통과한다. */
    public static final String BUCKET_LABEL = "labels";
    public static final String BUCKET_SELFIE = "selfies";

    private final RestClient http;
    private final String anonKey;
    private final String baseUrl;

    public StorageClient(@Value("${barum.supabase.url}") String supabaseUrl,
                         @Value("${barum.supabase.anon-key}") String anonKey) {
        this.anonKey = anonKey;
        this.baseUrl = supabaseUrl + "/storage/v1";
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(Duration.ofSeconds(3));
        f.setReadTimeout(Duration.ofSeconds(15));
        this.http = RestClient.builder()
                .baseUrl(supabaseUrl + "/storage/v1")
                .requestFactory(f)
                .build();
    }

    private RestClient.RequestHeadersSpec<?> auth(RestClient.RequestHeadersSpec<?> spec, String jwt) {
        return spec.header("apikey", anonKey).header("Authorization", "Bearer " + jwt);
    }

    /**
     * Supabase는 서명 URL을 {@code /object/...} 상대경로로 돌려준다.
     * 그대로 내보내면 프론트가 Storage 베이스 URL을 알아야 하므로 절대 URL로 만들어 준다.
     */
    private String absolute(Object relative) {
        String s = String.valueOf(relative);
        return s.startsWith("http") ? s : baseUrl + (s.startsWith("/") ? s : "/" + s);
    }

    /**
     * 업로드용 서명 URL. 프론트가 여기로 직접 PUT 한다.
     *
     * <p>{@code x-upsert}가 없으면 이미 있는 경로에 대해 <b>서명 발급 단계에서</b> 409가 난다.
     * 셀카 경로가 {@code {userId}/{날짜}.jpg}라서 같은 날 다시 찍으면 바로 걸린다
     * (화면 2·10의 "다시 촬영"). PUT이 아니라 URL 발급이 실패하는 거라 원인을 찾기 어렵다.
     */
    @SuppressWarnings("unchecked")
    public String signedUploadUrl(String jwt, String bucket, String path) {
        Map<String, Object> res = (Map<String, Object>) auth(
                http.post().uri("/object/upload/sign/{bucket}/{path}", bucket, path)
                        .header("x-upsert", "true"), jwt)
                .retrieve().body(Map.class);
        return absolute(res.get("url"));
    }

    /** 조회용 서명 URL 여러 개를 한 번에. 타임라인 30건에 30번 부르지 않는다. */
    @SuppressWarnings("unchecked")
    public Map<String, String> signedUrls(String jwt, String bucket, List<String> paths, int expiresIn) {
        Map<String, String> out = new HashMap<>();
        if (paths.isEmpty()) {
            return out;
        }
        try {
            List<Map<String, Object>> res = (List<Map<String, Object>>) auth(
                    http.post().uri("/object/sign/{bucket}", bucket)
                            .body(Map.of("expiresIn", expiresIn, "paths", paths)), jwt)
                    .retrieve().body(List.class);
            for (Map<String, Object> r : res) {
                Object signed = r.get("signedURL");
                Object path = r.get("path");
                if (signed != null && path != null) {
                    out.put(String.valueOf(path), absolute(signed));
                }
            }
        } catch (Exception e) {
            // 썸네일이 없다고 타임라인 전체가 실패하면 안 된다. 해당 항목만 null로 나간다
            log.warn("Signed URL 발급 실패 (bucket={}): {}", bucket, e.toString());
        }
        return out;
    }

    /** 지정한 경로들을 지운다. 실패해도 예외를 올리지 않는다 — 삭제 흐름 전체가 멈추면 안 된다. */
    public int deleteObjects(String jwt, String bucket, List<String> paths) {
        if (paths.isEmpty()) {
            return 0;
        }
        try {
            auth(http.method(org.springframework.http.HttpMethod.DELETE)
                    .uri("/object/{bucket}", bucket)
                    .body(Map.of("prefixes", paths)), jwt)
                    .retrieve().toBodilessEntity();
            return paths.size();
        } catch (Exception e) {
            log.warn("Storage 삭제 실패 (bucket={}, {}건): {}", bucket, paths.size(), e.toString());
            return 0;
        }
    }

    /** 사용자 폴더 전체 삭제. 데이터 전체 삭제(원칙 5의 삭제 정책)에 쓴다. */
    @SuppressWarnings("unchecked")
    public int deleteUserFolder(String jwt, String bucket, String userId) {
        try {
            List<Map<String, Object>> files = (List<Map<String, Object>>) auth(
                    http.post().uri("/object/list/{bucket}", bucket)
                            .body(Map.of("prefix", userId, "limit", 1000)), jwt)
                    .retrieve().body(List.class);
            if (files == null || files.isEmpty()) {
                return 0;
            }
            List<String> paths = new ArrayList<>();
            for (Map<String, Object> f : files) {
                paths.add(userId + "/" + f.get("name"));
            }
            return deleteObjects(jwt, bucket, paths);
        } catch (Exception e) {
            log.warn("Storage 폴더 조회 실패 (bucket={}): {}", bucket, e.toString());
            return 0;
        }
    }
}
