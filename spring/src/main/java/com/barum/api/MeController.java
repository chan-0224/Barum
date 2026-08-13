package com.barum.api;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.barum.client.StorageClient;
import com.barum.config.SecurityConfig;
import com.barum.db.Rls;

/**
 * API.md 12 — 내 데이터 전체 삭제 (화면 13).
 *
 * <p>제품·기록·업로드 이미지를 전부 지운다. 얼굴 사진이 남으면 삭제 기능이라 할 수 없다(원칙 5).
 * 심사에서 개인정보 질문이 나오면 이 엔드포인트가 답이다.
 */
@RestController
@RequestMapping("/api/v1/me")
public class MeController {

    private static final Logger log = LoggerFactory.getLogger(MeController.class);

    private final Rls rls;
    private final StorageClient storage;

    public MeController(Rls rls, StorageClient storage) {
        this.rls = rls;
        this.storage = storage;
    }

    @DeleteMapping("/data")
    public ResponseEntity<Void> deleteAll() {
        String userId = SecurityConfig.currentUserId();
        String jwt = SecurityConfig.currentJwt();

        // 파일을 먼저 지운다. DB 행이 남아 있어야 selfie_path를 알 수 있는 건 아니지만,
        // 폴더 단위로 지우므로 순서는 무관하고 실패해도 DB 삭제는 진행한다
        int selfies = storage.deleteUserFolder(jwt, StorageClient.BUCKET_SELFIE, userId);
        int labels = storage.deleteUserFolder(jwt, StorageClient.BUCKET_LABEL, userId);

        int[] deleted = rls.asUser(userId, jdbc -> new int[]{
                // product_ingredients는 on delete cascade로 따라 지워진다
                jdbc.update("delete from products"),
                jdbc.update("delete from daily_records"),
        });

        log.info("데이터 전체 삭제 — 제품 {}건, 기록 {}건, 셀카 {}개, 라벨 {}개",
                deleted[0], deleted[1], selfies, labels);
        return ResponseEntity.noContent().build();
    }
}
