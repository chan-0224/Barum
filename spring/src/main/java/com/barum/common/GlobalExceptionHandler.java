package com.barum.common;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/** 모든 에러를 docs/API.md 형식 {code, message}로 통일한다. */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    private ResponseEntity<Map<String, String>> body(ErrorCode code, String message) {
        return ResponseEntity.status(code.status())
                .body(Map.of("code", code.name(), "message", message));
    }

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Map<String, String>> handleApi(ApiException e) {
        return body(e.code(), e.getMessage());
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, MethodArgumentTypeMismatchException.class})
    public ResponseEntity<Map<String, String>> handleValidation(Exception e) {
        return body(ErrorCode.VALIDATION_ERROR, ErrorCode.VALIDATION_ERROR.message());
    }

    /**
     * 본문 JSON이 깨졌거나 타입이 안 맞는 경우. 잡지 않으면 마지막 그물에 걸려
     * 502 EXTERNAL_API_ERROR로 나가는데, 그러면 클라이언트 잘못인데 서버 장애로 보고하는 셈이라
     * 프론트가 성공할 리 없는 재시도를 반복한다.
     */
    @ExceptionHandler(org.springframework.http.converter.HttpMessageNotReadableException.class)
    public ResponseEntity<Map<String, String>> handleUnreadable(Exception e) {
        return body(ErrorCode.VALIDATION_ERROR, "요청 본문을 읽을 수 없습니다.");
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Map<String, String>> handleNotFound(NoResourceFoundException e) {
        return body(ErrorCode.VALIDATION_ERROR, "존재하지 않는 경로입니다.");
    }

    /**
     * RLS 위반(SQLSTATE 42501). Spring이 BadSqlGrammarException으로 감싸므로 기본 핸들러에
     * 두면 502 EXTERNAL_API_ERROR로 나간다 — 프론트는 "외부 API 실패"로 해석해 재시도하고,
     * 성공할 리 없는 재시도를 반복한다. 그래서 따로 잡는다.
     *
     * <p>우리 설계에서는 쓰기 시 user_id를 항상 검증된 JWT에서 채우므로 <b>이게 뜨면 서버 버그다.</b>
     * 그래서 ERROR로 남긴다. 다만 클라이언트에게는 "네 것이 아니다"가 정확한 답이라 404를 준다.
     */
    @ExceptionHandler(org.springframework.dao.DataAccessException.class)
    public ResponseEntity<Map<String, String>> handleDataAccess(
            org.springframework.dao.DataAccessException e) {
        if (isRlsViolation(e)) {
            log.error("RLS 위반 — 코드가 소유하지 않은 행을 쓰려 했다", e);
            return body(ErrorCode.PRODUCT_NOT_FOUND, "요청한 데이터를 찾을 수 없습니다.");
        }
        log.error("DB 오류", e);
        return body(ErrorCode.EXTERNAL_API_ERROR, "일시적인 오류가 발생했습니다.");
    }

    private boolean isRlsViolation(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof java.sql.SQLException sql && "42501".equals(sql.getSQLState())) {
                return true;
            }
            if (t == t.getCause()) {
                break;
            }
        }
        return false;
    }

    /**
     * 마지막 그물. 스택트레이스는 서버 로그에만 남기고 클라이언트에는 코드만 준다.
     * 예외 메시지를 그대로 흘리면 DB 구조나 내부 URL이 노출된다.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, String>> handleUnexpected(Exception e) {
        log.error("처리되지 않은 예외", e);
        return body(ErrorCode.EXTERNAL_API_ERROR, "일시적인 오류가 발생했습니다.");
    }
}
